# Memecoin Agent

Solana + BSC + Robinhood 链智能跟单系统 — 基于链上 Smart Money 信号的自动化交易框架。

## 核心功能

- **Smart Money 跟踪** — OKX DEX V6 REST `signal/list` 主链路，按链轮询最新信号
- **持仓实时价格** — OKX DEX V6 REST `market/price` 批量查询；WS 仅保留兼容代码
- **安全评分开仓** — 买入前 5 维评估（蜜罐/税率/冲击/流动性/持币集中度）
- **快速退出** — 默认 +10% 全仓退出；旧阶梯模式可通过 `FAST_EXIT_MODE=0` 启用
- **多维风控** — 止损 -8%、soldRatio 跟卖、最大持仓时间和连续止损冻结
- **三链市场数据** — Solana(501)、BSC(56)、Robinhood(4663) 统一走 OKX DEX V6 REST；BAW BSC 执行器默认暂停
- **按链策略配置** — Dashboard 可分别设置三条链的市值门槛、共识钱包、单笔金额、止损、止盈和持仓上限
- **交易历史** — 完整记录每笔买入到卖出的 PnL、持有时间、出场原因

## 架构

```
OKX DEX V6 REST signal/list（501 Solana + 56 BSC + 4663 Robinhood）
    ↓
realtime_sm_monitor.py ← 主循环
    ├── 持仓价格: OKX V6 REST market/price
    ├── 安全检查: safety_check.py (5 维评分, score≥70 开仓)
    ├── 买入/卖出: DRY-RUN 默认只记账；实盘执行需显式启用对应执行器
    ├── BSC BAW: BSC_BAW_ENABLED=1 才启用，默认暂停
    ├── Robinhood: 当前接入 OKX 市场数据，暂不启用真实钱包/交易执行器
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
- OKX DEX WebSocket V6（`wss://wsdex.okx.com/ws/v6/dex`）
- `kol_smartmoney-tracker-activity`：Smart Money/KOL 动态，字段在 V6 `data[]`
- `dex-market-new-signal-openapi`：新信号，按单链 `chainIndex` 订阅，字段在 V6 `arg`
- `scripts/ws_price_feed.py` 仅作为旧启动器的 V6 兼容入口；价格订阅必须使用 `chainIndex` + `tokenContractAddress`
- 只有登录成功且至少一个入场频道订阅成功，才视为 WS 入场源可用；否则自动 REST 兜底
- 信号频道需要 OKX 侧权限/白名单，`60029` 不会再被误判为“WS 已就绪”
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

设置 `FAST_EXIT_MODE=0` 后，才启用旧的多层时间/阶梯止盈逻辑。当前持仓价格统一通过 OKX DEX V6 REST `market/price` 查询。

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
- **链范围**：Solana + BSC + Robinhood（市场数据）

## 快速开始

### 环境要求
- Python 3.7+
- `requirements.txt` 中的 `websocket-client`
- onchainos CLI（`~/.local/bin/onchainos.exe`）
- BAW CLI（仅在 `BSC_BAW_ENABLED=1` 的 BSC 实盘执行场景需要）
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

浏览器打开 `http://127.0.0.1:8765/`。看板读取模拟盘状态、运行心跳和交易日志，每 2 秒刷新；“运行配置”区域只允许提交经过边界校验的策略参数，不提供下单控制。

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

`BSC_BAW_ENABLED=0`（默认）暂停 BAW；BSC 信号和价格仍由 OKX DEX V6 REST 提供。
只有明确设置 `BSC_BAW_ENABLED=1`，才允许 BSC BAW 钱包余额、限价单和交易路径参与实盘流程。

运行中的策略参数可以直接在 Dashboard 修改。选择 Solana、BSC 或 Robinhood 后，配置只作用于所选链；选择“全局”时可修改日/月亏损上限和轮询周期。配置会写入 `data/sm_runtime_config.json`，由模拟盘下一轮轮询读取，无需重启。

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
