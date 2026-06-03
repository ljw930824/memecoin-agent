# 长期记忆（精简版）

## 用户偏好
- 语言: 中文优先 | 回复: 只说重点，格式化输出
- 通知: Telegram，仅成交/持仓变动时推送
- **git commit 习惯**: 每次代码改动必须 git commit
- **交易失败零容忍**: 下单失败立即重试（≤3次），开仓后必挂止盈限价单
- **SOP**: 策略改动 → 模拟交易 → 推报告 → 确认后开实盘
- 总资金量少时风险可放大

## 活跃策略 → [STRATEGY.md](STRATEGY.md)
v3.3 REST tracker + 阶梯出本 + soldRatio 过滤
- 入场: ≥2 高胜率钱包(wr≥50%) + mcap≥$15K + soldRatio<30% + safety_check≥50
- 出场: SM跟卖 / SL -8% / 阶梯出本
- 风控: 动态日亏降级 / 连续3SL冻结2h / 买入后12s检查
- 单笔$5 | 最大持仓3 | Solana优先 | watchdog 10s
- v3.4 REST tracker + 5层阶梯止盈 + soldRatio过滤 + WS price_cache + dedup修复

## 工具备忘录 → [TOOLS.md](TOOLS.md)
- onchainos: swap execute/quote, wallet balance
- baw CLI v1.0.9: market-order swap, wallet balance
- QClaw: config.patch 写入配置

## 外部索引
- 策略详细参数: [STRATEGY.md](STRATEGY.md)
- Telegram排查指南: `memory/telegram-troubleshooting-guide.md`
- 历史回测数据: `memory/archive/`
- 每日日志: `memory/YYYY-MM-DD.md`

## 核心经验（仅保留原则性结论）

| 领域 | 关键经验 |
|------|---------|
| **Telegram** | `grammy`三件套缺失是入站故障主因；QClaw升级后需手动重装；`gateway restart`不够，必须完全退出重启 |
| **API** | BAW success≠链上成功；onchainos JSON路径为`data.details[].tokenAssets[]` |
| **编码** | Windows Python需`sys.stdout.reconfigure(encoding='utf-8')` |
| **风控** | PnL%简单加总无意义，真实ROI=总利润USD/总投入USD |
- Stop Loss 实际触发-11.8%远超设定-8%，60s轮询间隔导致检测延迟是亏损主因（127笔SL亏$498.8）
- Breakeven Dust层平均触发+11.0%全是盈利，截流阶梯TP层，错过了+30%/+100%机会

## 当前活跃项目

| 项目 | 状态 | 待决策 |
|------|------|--------|
| v3.3模拟盘 | 运行中，信号全被过滤 | 是否调 MIN_CONSENSUS_WALLETS 2→1？ |
| WS价格流 | ✅正常 | 待回测验证 price_cache 效果 |
| 回测脚本 | 已编写 | 执行历史回测分析阈值敏感性 |
- 当前活跃项目：v3.3模拟盘运行中信号全被过滤、WS价格流✅正常price_cache已实现、回测脚本已编写待执行33条历史信号回测

## 安全规则
- **禁止展示 API Key / Token / Secret**
- 已知凭证来源: OKX, Telegram, WeChat, Gateway, mimo-plan

## v3.3策略补丁

- WS price_cache已实现: fetch_tracker()消费WS事件时同步更新_price_cache，get_token_price_usd()改为cache-first优先读10s内缓存，miss才调REST

## 模拟盘诊断结论

- 策略从第2天开始退化: Day1 +$10.58 → Day2 +$1.37 → Day3+亏损/停摆; 信号质量下降或micro-cap拉低整体
- 2026-05-27~29模拟盘统计：51笔交易，胜率57%，平均PnL+2.57%，最大盈利+47.5%（czbot），最大亏损-23.3%（日拱一卒重复买入Bug）；另2026-06-02排查发现_record_trade()未调用导致95 BUY+181 SELL记录丢失，平仓信息未持久化到state

## 优化方向

- 优化方向：P0轮询优化60s→15s+并行价格获取（待实施）；P1收紧SL被否定（治标不治本）；P2删除BD层被否定（最高ROI层）；P3 SL grace period前5分钟不检查SL（待实施）；v3.4已实现5层阶梯止盈替代原breakeven_dust
- 已提出优化建议：MIN_SAFETY_SCORE 50→60提升入场质量、STOP_LOSS_PCT -8%→-6%更快止损、或接入WS价格流做10s级止损

## 网络环境

- 网络受限: price.jup.ag/jup.ag DNS被VPN劫持(198.18.x.x)，api.dexscreener.com HTTP 404，stream.binance.com:9443 WS无数据，无法直连外部公开WebSocket

## OKX DEX WebSocket

- OKX DEX v6 WS可行: 10秒收到2笔事件，能接收SM实时交易信号+成交价格，但不能直接获取任意token当前价格(非orderbook行情流); tokenPrice字段在事件中但realtime未消费

## 模拟盘状态

- 2026-05-27重置: 清空trade_history(331→0)，重置daily_pnl/consec_sl/freeze，保留wallets/seen_txs/perm_fail_tokens; WS连接成功但所有信号被过滤
- 2026-06-03 持久化补丁验证通过：_save_trade_history()末尾注入save_state(state)后，trade_history从5条→26条（新增21条），重启后数据不丢失
- 2026-06-02 fix遇到Windows换行符(\r\n)导致edit工具匹配失败，改用Python脚本直接修复缩进
- 2026-06-03 模拟盘重启成功（PID 64272），state文件每12s更新（price_cache补丁生效），发现3个残留进程占sm_wallets.json文件锁→全部杀掉后重启
- 2026-06-03 新增21笔交易统计：胜率43%（9胜/12负），平均PnL+2.7%，最佳亮剑出击+37.7%，最差STOCK -14.1%，止损滞后严重（12笔止损多在-8%~-14%，60s轮询根因）
- 当前持仓3个：C6pTso...pump PnL -2.4%持仓0.8h、HMGi31...pump PnL +3.7%持仓0.2h、0x1e905...ffff PnL+0.0%刚买入
- daily_pnl显示0.0异常，可能计算逻辑有问题，待排查

## 当前项目与关注

- v3.4 补丁 2026-05-29 实施：修复重复买入死代码（_check_shared_dedup 移到 continue 前）、删除 POST-BUY 12s 延迟检查、新增 5 层阶梯止盈（quick_tp +10% 卖 30% / 6h_tp 无SL +30% 卖 40% / 12h_tp SL -5%/+15% 卖 80% / 24h_exit SL -3%/+5% 卖 100% / 48h_force 强制出场）、session_bought 去重
- 模拟盘 PID 45476 运行中（dryrun），WS 连接正常，4758 钱包追踪，positions 为空等待共识信号
- 信号过滤主要瓶颈是共识钱包数量不足（consensus fail good=1 need≥2），不是 MIN_MCAP/MIN_SCORE，信号走不到 safety check 那步
- 回测数据盘点：sm_wallets.json（5.9MB 2689 钱包）✅、signal-history.json（33 条历史信号）✅、sm_trade-log_dryrun.txt（14K 行非结构化）⚠️ 需解析，_backtest_historical.py 已编写未执行
- price_cache 补丁已实现：fetch_tracker() 消费 WS 事件时同步更新 _price_cache，get_token_price_usd() 改为 cache-first 优先读 10s 内缓存，miss 才调 REST
- 2026-05-28 已清理 MEMORY.md 冗余区块，建立 archive 目录和 INDEX.md 索引，建立防膨胀机制：新经验先写每日日志，月度归档时才提取核心原则
- 定时推送已全部取消（Telegram），用户清理了所有相关任务
- 模拟盘PID 64276运行中（dryrun），WS连接正常，state每12s更新（price_cache生效），信号过滤瓶颈仍是共识钱包不足（consensus fail good=1 need≥2）
- 信号过滤瓶颈是共识钱包数量不足（consensus fail good=1 need≥2），不是MIN_MCAP/MIN_SCORE，信号走不到safety check那步
- WS价格流✅正常，price_cache补丁已实现待持仓出现时验证效果

## 经验与决策

- 2026-05-27~29模拟盘统计：51笔交易，胜率57%，平均PnL+2.57%，最大盈利+47.5%（czbot），最大亏损-23.3%（日拱一卒，重复买入Bug导致），breakeven_dust占比57%过高
- 重复买入 Bug 根因：_check_shared_dedup() 在 continue 之后是死代码从未执行，导致同一 token 被买两次（日拱一卒 -23.3% 案例），v3.4 已修复
- breakeven_dust 层 +5% 卖 77% 太激进，57% 场次都是 breakeven_dust 出场，止盈阶梯未充分跑完，错过 +30%/+100% 机会；v3.4 改为 5 层阶梯止盈
- 重复买入Bug根因：_check_shared_dedup()在continue之后是死代码从未执行，导致同一token被买两次（日拱一卒-23.3%案例）；另发现_record_trade()未调用导致平仓记录丢失，_save_trade_history()末尾缺save_state()
- state持久化bug：_record_trade()未被调用，导致95笔BUY+181批SELL在重启后丢失；根因是_save_trade_history()末尾缺少save_state()调用
- POST-BUY安全网效果：~95 SM BUY信号中有~11笔触发DUMP即时止损（最大-37.8%），session_bought去重正常
- SQLite可提升state持久化健壮性（防json损坏、原子写入），但不能修复逻辑bug（如缺失的_record_trade调用）；优先级P0先修收_record_trade/save_state，P1可选升级SQLite
- 2026-06-03 _save_trade_history()持久化补丁验证通过：函数末尾注入save_state(state)后，trade_history从5条→26条重启后不丢失（之前根因：_record_trade()未被调用+_save_trade_history()末尾缺save_state()→95笔BUY+181批次SELL丢失）

## Promoted From Short-Term Memory (2026-06-01)

- **目标**: 提升模拟盘成交率、止损响应速度、SM 跟单效率
- **已应用补丁** (realtime_sm_monitor.py):

## Promoted From Short-Term Memory (2026-06-03)

- **文件**：`scripts/active/realtime_sm_monitor.py`
- 备份文件：realtime_sm_monitor.py.bak_ws_price；启动参数：--mode dryrun --loop 60 --rounds 999999
- **启动命令**：`$env:PYTHONUNBUFFERED='1'; python -u scripts/active/realtime_sm_monitor.py --mode dryrun 2>&1` **启动参数**：`--mode dryrun --loop 60 --rounds 999999`
