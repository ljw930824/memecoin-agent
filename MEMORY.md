# 长期记忆（精简版）

## 用户偏好
- 语言: 中文优先 | 回复: 只说重点，格式化输出
- 通知: Telegram，仅成交/持仓变动时推送
- **git commit 习惯（2026-05-16确立）**：每次代码改动必须 git commit，记录改动说明
- **交易失败零容忍**: 下单失败必须立即重试（≤3次），记录 retry-log.txt
- **真金白银保护**: 开仓后必须挂止盈限价单，失败则立即 rollback
- **SOP**: 策略改动 → 模拟交易 → 推报告 → 确认后开实盘

## 活跃策略（v3.2 REST tracker + 阶梯出本 + soldRatio）
- **数据源: 直连OKX DEX WS v6（主源，实时推送）+ REST tracker（兜底，30s轮询）** + soldRatio 过滤
- 入场: ≥2 高胜率钱包（wr≥50%）买入同一 token + mcap ≥ $10K + soldRatio < 30% + 价格趋势过滤（极端暴跌3min >8%/min → SKIP，正常/上涨/无数据 → 放行）
- 出场: SM ≥3 笔卖出跟卖 / SL -8% / **保本优先阶梯**（非固定 TP）
  - +30% → 卖77%（回本），剩23%免费持仓
  - +100% → 再卖50%（收利润）
  - +300% → 再卖50%（博大奖）
  - soldRatio ≥50% → 全仓卖出
  - soldRatio ≥30% → 卖50%
  - 时间加权：6h +30%/50%卖，12h +15%/全卖，24h +5%/全卖，48h强平
- 单笔: $5 | 最大持仓: 3 | 链: Solana + BSC
- 风控: 动态风险调整（基础2%风险系数，日亏>2%降到1.5%，>3.5%降到1%，>5%停止交易） | 连续 3 SL 冻结 2h | 时间加权止损（6h/-5%, 12h/-3%, 24h/保本, 48h/强平）
- watchdog.ps1 (Task Scheduler 每2分钟检查进程存活，-WindowStyle Hidden 隐藏运行，dead自动重启)
- State 文件: 实盘 `sm_monitor_state.json`，模拟盘 `sm_monitor_state_dryrun.json`（已分离）
- 买入前安全检查: safety_check.py 五维评分（蜜罐30/税率15/冲击15/流动性25/持币集中度15），score>=40 开仓，>=60 优先，Solana+BSC 双链共享
- Sim/Monitor主循环已添加错误处理：run_once()包裹try/except，API错误不再杀进程，自动保存状态+3x sleep后重试
- v3.2策略审计发现的4个缺失功能已补齐：(1)跨链去重shared_bought.json(1h TTL) (2)连续3SL冻结2h (3)soldRatio监控(≥50%skip，≥30%consensus+1) (4)+5%保本阶梯（TIME_TIERS第一档卖77%）

## 工具备注
- baw CLI v1.0.9: `market-order swap` / `limit-order sell`（旧 `defi` 废弃）
- onchainos 价格: 用 `token price-info`（不用 swap quote，是缓存值）
- **OKX DEX WS v6 直连（2026-05-16启用）**：端点 `wss://wsdex.okx.com/ws/v6/dex`，HMAC-SHA256认证，频道 `kol_smartmoney-tracker-activity`，auto-reconnect。**用非PROD凭证（OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE），PROD凭证（OKX_PROD_*）不适用DEX**
- WS为主数据源（`okx_dex_ws.py`模块），REST tracker为兜底。tradeType="1"=buy, "2"=sell（与REST一致，无需转换）
- State文件已分离：execute_bsc.py→smart-money-bsc-state.json，execute_solana.py→smart-money-sol-state.json，monitor_positions.py合并读写两个文件，跨链去重通过shared_bought.json
- 死仓位修复：check_positions中两个死仓检测点改为to_sell_all（走正常卖出路径），不再直接pop不卖
- openclaw.json 递归 bug，CLI cron 不可用，改用 Task Scheduler。直接手动编辑openclaw.json不可靠（疑似OneDrive重定向或QClaw进程持续覆盖），需用`config.apply`写入配置
- Telegram插件重启规则（2026-05-12确认，05-13升级验证）：SIGUSR1(gateway restart)不会重新执行channel的startAccount，只重载配置。若插件首次加载时因依赖缺失失败，后续SIGUSR1不会恢复。必须完全退出QClaw进程再启动。**每次QClaw升级后必须重新安装Telegram三件套**（升级重置node_modules目录），升级也可能重置openclaw.json需检查channels.telegram和plugins.telegram配置
- **Telegram插件依赖三件套**：`grammy`（核心）+ `@grammyjs/runner`（long polling）+ `@grammyjs/transformer-throttler`（节流），安装目录：`D:\Program Files\QClaw\resources\openclaw\node_modules\openclaw\node_modules\`
- **`openclaw plugins list` 显示loaded≠插件可用**：load和register是两阶段，loaded只代表文件加载成功，register失败时静默跳过（无日志）
- **`openclaw doctor --fix` 漏检grammy核心包**：只检测@grammyjs/runner和transformer-throttler，不检测grammy本身
- **诊断Telegram入站是否工作**：检查 `~\.qclaw\telegram\update-offset-default.json` 是否存在（polling运行才会创建），或Bot API `getWebhookInfo` 的 `pending_update_count` 是否递减
- QClaw进程内存压力大时openclaw pairing list会OOM崩溃
- Telegram配置备份位置：C:\Users\dell\.qclaw\config_backup\telegram_config.json
- 详细排查指南：`memory/telegram-troubleshooting-guide.md`
- qclaw/modelroute是QClaw后端智能路由服务，不支持路由到自定义模型（服务端决定模型，客户端无法控制），底层模型选择对客户端不透明，无法知道实际调用了哪个模型。替代方案：primary+fallback降级/路由Agent意图分类/多Agent手动分流。当前primary=custom-1778258380132/kimi-k2.6（2026-05-14已切换到nvidia/minimaxai/minimax-m2.7）
- openclaw.json修改不会自动应用到已有会话，需完全退出QClaw重启，新会话才使用新配置
- 直接手动编辑openclaw.json不可靠（疑似OneDrive重定向或QClaw进程持续覆盖），需用`config.apply`写入配置
- OpenClaw v2026.4.21无用户可配置的planner设置，内部有activation-planner（插件激活）和credential-planner（凭证管理）但都不可配置
- OpenClaw内置loopDetection机制（默认关闭），已开启激进阈值：warning(8)/critical(15)/circuitBreaker(25)/unknownTool(5)，三种检测器(genericRepeat/knownPollNoProgress/pingPong)，配置路径`agents.list.QClaw.tools.loopDetection`，config.apply后SIGHUP热重载即生效，防止无限循环烧钱
- OpenClaw thinkingDefault字段是枚举值非布尔值，可选：off/minimal/low/medium/high/xhigh/adaptive/max；reasoning:false只控制不向用户展示思考过程，thinkingDefault:"off"才禁止向API发送thinking block，两者完全不同
- DeepSeek推理模型(deepseek-v4-pro等R1类)始终返回reasoning_content，OpenClaw不支持在后续请求中回传该字段导致API报错，唯一方案换用非推理模型deepseek-chat(DeepSeek-V3)
- NVIDIA API已配置为OpenAI兼容provider，provider名nvidia，Base URL https://integrate.api.nvidia.com/v1，示例模型nvidia/llama-3.1-nemotron-70b-instruct

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

## 用户身份与偏好

- 总资金量少的话，风险可以放大
- 技能安装来源：2026-05-08从GitHub克隆binance/binance-skills-hub和okx/onchainos-skills仓库，复制到C:\Users\dell\.qclaw\skills\，openclaw.json启用后重启Gateway完成安装
- [2026-05-12] Telegram入站故障彻底解决。**两次故障，同一根因模式**：
  1. **5/9故障**：QClaw进程OOM→插件未正常初始化→SIGUSR1 restart无法恢复→**完全退出重启后修复**
  2. **5/11-12故障**：grammy核心包缺失→插件register阶段静默失败→doctor漏检→安装grammy后仍需**完全退出重启**才生效（SIGUSR1不够）
  - **核心教训**：任何Telegram入站问题→先尝试完全退出QClaw重启，不要依赖gateway restart
  - 安装grammy命令：`cd "D:\Program Files\QClaw\resources\openclaw\node_modules\openclaw" && npm install grammy --save --legacy-peer-deps`
  - 排查指南：`memory/telegram-troubleshooting-guide.md`
- 放弃OpenRouter（费用原因），`qclaw/modelroute`不支持路由到自定义模型，替代方案：primary+fallback降级/路由Agent意图分类/多Agent手动分流，当前primary=custom-1778258380132/kimi-k2.6
- 当前模型配置：agents.defaults.model.primary = custom-1778258380132/kimi-k2.6，modelroute路由不可控是已知的痛点

## 当前项目与关注

- BAW持仓与monitor显示不一致问题：BAW有4个BSC持仓但monitor显示0持仓，BAW持续买入但state没有记录
- sm_trade-log_dryrun.txt是纯文本日志格式（[HH:MM:SS]开头），非JSON格式
- 三件紧急数据管理任务已完成：(1)归档集成auto_archive+on_sell_closed到sim/monitor (2)日志轮转日期前缀+5MB自动轮转+30天删除 (3)钱包精简丢弃recent_trades，7.2MB→253KB(29倍压缩)
- strategy-todos.md中待完成的5项v3.1增强和2项安全检查增强，详见'当前项目与关注'章节
- 安全检查增强待完成：Solana持币集中度需接入链上数据查询top holders、BSC安全检查需验证BAW CLI quote返回结构
- 策略待办v3.1增强5项：(1)cooldown数据流打通 (2)spread过滤生效 (3)ACTIVE状态分级评分改为时间敏感型 (4)MIN_SM_ENTRIES/MIN_MARKET_CAP硬性过滤 (5)timeout age tiers实现
- Orchestrator v3.2同步状态：signal_listener.py评分升级到v3.2(spread/chase/stale/SM过滤)，execute_bsc.py和execute_solana.py已加入风控(日亏-15%/连续3SL冻结2h)+trailing stop；代码改完、语法通过、未开启任务、未开启实盘
- Orchestrator v3.2回测结果：旧队列v2通过19/26，v3.2通过0/26（队列数据过旧导致测试无效）
- [2026-05-13] SOL交易代码全面审查待完成，用户两次催促(14:03+14:19)但尚未执行，需排查execute_solana.py等Solana交易代码遗留问题
- [2026-05-13] 尝试在openclaw.json添加experimental.planTool:false失败（多种编辑方式报告成功但文件未变更），OpenClaw版本2026.4.21无用户可配置的planner设置
- [2026-05-14] DeepSeek推理模式故障已诊断：deepseek-v4-pro是推理模型始终返回reasoning_content，但OpenClaw不会回传，唯一解法是换用非推理模型deepseek-chat(DeepSeek-V3)

## 技术规范偏好

- Sim运行超时需设置为~300s（原120s不够用），因sm_wallets_dryrun.json约10MB加载需1-2s，多次CLI调用累计可能超时
- BAW API success:true只表示订单提交不表示链上执行成功，onchainos JSON路径为data.details[].tokenAssets[]，baw wallet balance字段名是contractAddress不是address，Windows GBK编码需sys.stdout.reconfigure(encoding='utf-8')
- 数据格式必须文档化，金额vs百分比不能混淆（v3.2 bug: daily_pnl被误读）
- 信号监控频率已升级至1分钟，scalper v3.2功能验证8项中6项真实现2项stub已修复
- 脚本目录重组完成：active(9)/deprecated(27)/archive(20)/launchers(11)
- 推理模型(DeepSeek-V4-Pro等R1类)始终返回reasoning_content，OpenClaw不支持在后续请求中回传该字段导致API报错，唯一方案换用非推理模型deepseek-chat(DeepSeek-V3)

## 经验与决策

- 数据归档策略实现：901文件→180文件（-80%），按时间衰减保留（<24h全保留，24h-7d每小时1个，7d-30d每天1个，>30d删除）

## 交易历史

- 2026-04-26 BABYASTEROID(BSC) TP_HIT +$0.86(+12%)，bibi(BSC) SL_HIT -$0.66(-12.63%)，日累计P&L +$0.20
- 2026-04-28 FSP(BSC)手动关闭死持仓链上余额归零（疑似Rug）-$2.10，巨龙(BSC)脚本紧急清 entered $9.82 Score35，46分钟清算，总P&L -$1.90
- 2026-04-29 onchainos pump.fun验证：GOBLIN代币可交易但地址不能含i/o字符，execute_solana.py修复v2改用tokenUnitPrice和--readable-amount
- 2026-05-02 Signal List弃用原因：100% soldRatio>90%，信号到达时聪明钱已清仓；WebSocket测试失败（OKX WS reconnecting网络问题），策略升级至v3 REST tracker跟单版
