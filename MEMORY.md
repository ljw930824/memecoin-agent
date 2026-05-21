# 长期记忆（索引版）

## 用户偏好
- 语言: 中文优先 | 回复: 只说重点，格式化输出
- 通知: Telegram，仅成交/持仓变动时推送
- **git commit 习惯**: 每次代码改动必须 git commit
- **交易失败零容忍**: 下单失败立即重试（≤3次），开仓后必挂止盈限价单
- **SOP**: 策略改动 → 模拟交易 → 推报告 → 确认后开实盘
- 总资金量少时风险可放大

## 活跃策略 → [STRATEGY.md](STRATEGY.md)
v3.2 REST tracker + 阶梯出本 + soldRatio 过滤
- 入场: ≥2 高胜率钱包(wr≥50%) + mcap≥$10K + soldRatio<30% + safety_check≥40
- 出场: SM跟卖 / SL -8% / 阶梯出本(+30%→卖77%, +100%→卖50%, +300%→卖50%)
- 风控: 动态日亏降级 / 连续3SL冻结2h / 时间加权止损
- 单笔$5 | 最大持仓3 | Solana+BSC | watchdog 1min

## 工具备忘录 → [TOOLS.md](TOOLS.md)
- onchainos: swap execute/quote, wallet balance, token price-info
- baw CLI v1.0.9: market-order swap, wallet balance (BSC)
- QClaw: config.apply 写入配置, Task Scheduler 替代 cron

## 项目状态 → [memory/current-projects.md](memory/current-projects.md)

## 交易历史 → [memory/trade-history.md](memory/trade-history.md)

## 📋 其他文档索引
- Telegram 排查: `memory/telegram-troubleshooting-guide.md`
- 策略待办: `memory/strategy-todos.md`
- 每日日志: `memory/YYYY-MM-DD.md`

## 🔒 安全规则
- **绝对禁止在聊天中展示 API Key / Token / Secret**
- MEMORY.md 不存凭证明文
- 已知凭证（仅记录来源）: OKX, Telegram, WeChat, Gateway, mimo-plan
