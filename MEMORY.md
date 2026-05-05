# 长期记忆（精简版）

## 用户偏好
- 语言: 中文优先 | 回复: 只说重点，格式化输出
- 通知: Telegram，仅成交/持仓变动时推送
- **交易失败零容忍**: 下单失败必须立即重试（≤3次），记录 retry-log.txt
- **真金白银保护**: 开仓后必须挂止盈限价单，失败则立即 rollback
- **SOP**: 策略改动 → 模拟交易 → 推报告 → 确认后开实盘

## 活跃策略（v3.2 REST tracker + 阶梯出本 + soldRatio）
- 数据源: onchainos REST tracker activities（10s轮询）+ soldRatio 过滤
- 入场: ≥2 高胜率钱包（wr≥50%）买入同一 token + mcap ≥ $10K + soldRatio < 30%
- 出场: SM ≥3 笔卖出跟卖 / SL -8% / **保本优先阶梯**（非固定 TP）
  - +30% → 卖77%（回本），剩23%免费持仓
  - +100% → 再卖50%（收利润）
  - +300% → 再卖50%（博大奖）
  - soldRatio ≥50% → 全仓卖出
  - soldRatio ≥30% → 卖50%
  - 时间加权：6h +30%/50%卖，12h +15%/全卖，24h +5%/全卖，48h强平
- 单笔: $5 | 最大持仓: 3 | 链: Solana + BSC
- 风控: 日亏 -15% 暂停 | 连续 3 SL 冻结 2h | 时间加权止损（6h/-5%, 12h/-3%, 24h/保本, 48h/强平）
- 主脚本: `scripts/active/realtime_sm_monitor.py` | 安全检查: `scripts/safety_check.py`
- **状态**: LIVE 实盘运行中 | 当前持仓: RIV (~$5.23, +6.8%)
- State 文件: 实盘 `sm_monitor_state.json`，模拟盘 `sm_monitor_state_dryrun.json`（已分离）
- 买入前安全检查: safety_check.py 五维评分（蜜罐30/税率15/冲击15/流动性25/持币集中度15），score>=40 开仓，>=60 优先，Solana+BSC 双链共享

## 工具备注
- baw CLI v1.0.9: `market-order swap` / `limit-order sell`（旧 `defi` 废弃）
- onchainos 价格: 用 `token price-info`（不用 swap quote，是缓存值）
- 用户要求 WS 优先、REST 做备选/兜底 | 实际 WS 一直 reconnecting（OKX 网络/防火墙问题），REST tracker 做主源（30s 轮询，每次 50-100 笔）
- openclaw.json 递归 bug，CLI cron 不可用，改用 Task Scheduler

## 🔒 安全规则（2026-05-05 新增）
- **绝对禁止在聊天中展示 API Key、Token、Secret 等敏感凭证**
- config.get 返回的结果含明文凭证，禁止全文展示，只说明配置项名称和状态
- 若用户需要查看凭证，引导到本地文件 `~/.qclaw/openclaw.json` 自行查看
- MEMORY.md 中不存储任何 API Key / Secret / Token 明文
- 已知凭证列表（仅记录来源，不记录值）：mimo-plan API Key、OKX key/secret/passphrase、Telegram Bot Token、WeChat Token、Gateway Auth Token

## 详细文档
- 交易历史: `memory/trade-history.md`
- 待办事项: `memory/strategy-todos.md`
- 每日日志: `memory/YYYY-MM-DD.md`
