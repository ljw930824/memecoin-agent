# Memecoin Agent

Solana + BSC 链智能跟单系统 — 基于链上 Smart Money 信号的自动化交易框架。

## 核心功能

- **Smart Money 跟踪** — OKX DEX WebSocket 事件优先；仅在 WS 不可用时使用 REST tracker 兜底
- **持仓实时价格** — 按持仓动态订阅 OKX `price` 频道，价格事件直接触发止盈/止损检查
- **安全评分开仓** — 买入前 5 维评估（蜜罐/税率/冲击/流动性/持币集中度）
- **快速退出** — 默认 +10% 全仓退出；旧阶梯模式可通过 `FAST_EXIT_MODE=0` 启用
- **多维风控** — 止损 -8%、soldRatio 跟卖、最大持仓时间和连续止损冻结
- **双链支持** — Solana (onchainos) + BSC (BAW CLI)
- **交易历史** — 完整记录每笔买入到卖出的 PnL、持有时间、出场原因

## 架构

```
OKX DEX WebSocket smart-money activity（事件唤醒）
    ↓
realtime_sm_monitor.py ← 主循环
    ├── REST tracker fallback（WS 不可用时）
    ├── 持仓价格: OKX `price` channel（每个持仓动态订阅/取消）
    ├── 安全检查: safety_check.py (5 维评分, score≥70 开仓)
    ├── 买入: onchainos buy / BAW CLI market-order swap
    ├── 持仓监控: WS 实时价格 + soldRatio 过滤，REST 仅作兜底
    ├── 卖出: 快速止盈 / 跟卖 / SL / 持仓超时
    └── 状态: data/sm_monitor_state*.json (持仓 + 交易历史)
```

## 目录结构

```
.
├── scripts/
│   ├── active/                  # 生产脚本（当前使用中）
│   │   ├── realtime_sm_monitor.py   # WebSocket 跟单主脚本
│   │   ├── safety_check.py          # 5 维安全评分
│   │   ├── execute_solana.py        # Solana 链交易执行
│   │   ├── execute_bsc.py           # BSC 链交易执行
│   │   ├── monitor_positions.py     # 持仓 P&L 监控
│   │   ├── signal_fetch_once.py     # 信号采集
│   │   ├── scalper_orchestrator.py  # 编排器
│   │   └── api_health_check.py      # API 健康检查
├── tests/                       # 离线链路测试
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
- OKX DEX WebSocket tracker activity（主路径）
- 筛选条件：至少 1 个符合条件的钱包买入同一 token
- 市值门槛：mcap ≥ $30K
- 抛压过滤：soldRatio < 30%

### 安全检查（safety_check.py）
开仓前 5 维评分（满分 100），score ≥ 70 才允许开仓，≥ 80 优先：

| 维度 | 权重 | 说明 |
|------|------|------|
| 蜜罐检测 | 30 | 是蜜罐直接拒绝 |
| 税率检查 | 15 | buy+sell tax ≤ 5% 满分 |
| 价格冲击 | 15 | impact ≤ 2% 满分 |
| 流动性深度 | 25 | > $50K 满分，< $1K 拒绝 |
| 持币集中度 | 15 | top10 ≤ 50% 满分 |

## 出场策略

### 快速退出（默认）
| 触发条件 | 操作 | 目的 |
|----------|------|------|
| +10% | 全仓卖出 | 达到预期利润即退出 |

设置 `FAST_EXIT_MODE=0` 后，才启用旧的多层时间/阶梯止盈逻辑。价格事件来自每个持仓的 OKX `price` 订阅；订阅连接中断时，主循环会降级到 REST 价格查询。

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
- **日亏上限**：-5% 暂停当日交易
- **连续止损**：3 次 SL 冻结 2 小时
- **链范围**：Solana + BSC

## 快速开始

### 环境要求
- Python 3.7+
- `requirements.txt` 中的 `websocket-client`
- onchainos CLI（`~/.local/bin/onchainos.exe`）
- BAW CLI（`baw` 命令）
- Windows Task Scheduler

### 运行模拟盘主链
```powershell
python -u scripts/active/realtime_sm_monitor.py --dry-run
```

### 明确启用实盘
```powershell
python -u scripts/active/realtime_sm_monitor.py --live
```

### 带参数运行
```bash
# 单次执行（不循环）
python scripts/active/realtime_sm_monitor.py --dry-run --once
```

### Watchdog 启动
```powershell
.\scripts\active\watchdog.ps1
```

### 启动模拟盘与 Dashboard
```powershell
.\scripts\dashboard\start_simulation_dashboard.ps1
```

浏览器打开 `http://127.0.0.1:8765/`。看板只读读取模拟盘状态、运行心跳和交易日志，每 2 秒刷新；不会提供下单控制。

## 配置

主要配置通过环境变量覆盖：
```python
FAST_EXIT_MODE = True    # +10% 默认全仓退出
QUICK_TP_PCT = 0.10
QUICK_TP_SELL_PCT = 1.0
MAX_POSITIONS = 3        # 最大同时持仓
SL_PCT_BASE = 0.08       # 止损 -8%
MAX_HOLD_HOURS = 2
```

可选环境变量：`OKX_PRICE_CHANNEL=price`（低延迟价格）或
`OKX_PRICE_CHANNEL=price-info`（同时获取市值、流动性等信息）。

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
- 凭证通过环境变量配置；可用 `QCLAW_WORKSPACE` 覆盖工作区路径
- `.gitignore` 已排除 `data/`、`memory/`、`sessions/` 等敏感目录

## License

Private
