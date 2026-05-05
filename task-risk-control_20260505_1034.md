# 头寸管理 & 总风险控制

**时间**: 2026-05-05 10:34
**目标**: 添加动态仓位计算和日/月亏损限制到实时监控脚本

## 实现内容

### 新增常量
RISK_PCT = 0.01 (单笔风险系数 账户总资金 x 1%)
SL_PCT_BASE = 0.08 (基础止损幅度 8%)
MAX_BUY_SIZE = 10.0 (单笔最大买入 USD)
MIN_BUY_SIZE = 3.0 (单笔最小买入 USD)
MAX_DAILY_LOSS_PCT = 0.05 (日亏损上限 5%)
MAX_MONTHLY_LOSS_PCT = 0.10 (月亏损上限 10%)

### 新增函数
calc_buy_size(state): 动态仓位 = (USDT余额 + 持仓价值) x 1% / 8%，范围 -
check_risk_limits(state): 日亏>=5%拒绝开仓，月亏>=10%暂停7天

### 买入流程改动
check_risk_limits -> blocked? skip -> calc_buy_size -> execute_buy(chain, ca, dynamic_buy)

### 修改文件
- scripts/active/realtime_sm_monitor.py (5 changes)
- scripts/simulation/sm_monitor_sim.py (6 changes)
- Both: syntax PASS