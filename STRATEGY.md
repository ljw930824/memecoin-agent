# V3.2 策略文档

## 架构
- **数据源**: OKX DEX WS v6（主源）+ REST tracker（兜底 30s 轮询）
- **执行**: `realtime_sm_monitor.py` 单一脚本（信号+执行+仓位合并）
- **钱包**: OnChainOS (Solana) + BAW CLI (BSC)，独立链执行
- **State**: `sm_monitor_state.json`（实盘）/ `sm_monitor_state_dryrun.json`（模拟）
- **Watchdog**: `watchdog.ps1`（10s内部循环）+ Task Scheduler（1min兜底）

## 入场规则

### 信号筛选
1. ≥2 高胜率钱包（wr ≥ 50%）在买同一 token
2. Market Cap ≥ $10,000
3. soldRatio < 30%（SM 清仓占比过高则跳过）
4. 价格趋势过滤：3min 跌幅 > 8%/min → SKIP（极端暴跌过滤）
5. 跨链去重：1h TTL `shared_bought.json`

### 安全检查 (safety_check.py)
- **蜜罐检测 (30分)**: isHoneyPot → 0 分（降权不硬拒）
- **税率 (15分)**: ≤5% 满分，>10% 拒绝
- **价格影响 (15分)**: ≤2% 满分，>15% 拒绝
- **流动性 (25分)**: >$50K 满分，<$1K 拒绝
- **持币集中度 (15分)**: ≤50% 满分，>80% 拒绝（Solana 未知给保守分）
- **阈值**: score ≥ 40 开仓，≥ 60 优先

### 风控限制
- **动态日亏**: >2% → 风险系数 1.5%, >3.5% → 1%, >5% → 停止
- **连续止损**: 3 次 SL → 冻结 2h（按链隔离）
- **最大持仓**: 3 笔
- **单笔**: $5（`calc_buy_size` 受可用余额上限约束）
- **余额下限**: USDT 余额需 ≥ $3 才尝试买入

## 出场规则

### 阶梯出本（优先于固定 TP）
| 涨幅 | 卖出比例 | 逻辑 |
|------|---------|------|
| +30% | 77% | 回本，剩 23% 免费持仓 |
| +100% | 再卖 50% | 收利润 |
| +300% | 再卖 50% | 博大奖 |

### SM 跟卖
- ≥3 笔 SM 卖出 → 全仓跟卖

### soldRatio 监控
- soldRatio ≥ 50% → 全仓卖出
- soldRatio ≥ 30% → 卖 50%

### 止损
- **硬止损**: -8%
- **时间加权止损**:
  - 6h: -5% | 12h: -3% | 24h: 保本 | 48h: 强平

### 卖出执行
- Solana: `onchainos swap execute --max-auto-slippage 25 --gas-level fast`
- 滑点重试: [25%, 35%, 49%] 三级降级
- 卖出优先用持仓存储余额，fallback 链上查询

## 钱包管理
- **reconcile_wallet**: 每轮同步链上持仓到 state
- **幽灵仓位清理**: 链上有但 state 无 → 自动卖出
- **黑名单**: `BLACKLIST_TOKENS` 防止异常 token 反复创建

## 数据管理
- **归档**: `data_archive_manager.py` 按时间衰减保留
- **日志轮转**: 5MB 阈值自动轮换，date prefix
- **钱包精简**: 7.2MB → 219KB（33x 压缩）
