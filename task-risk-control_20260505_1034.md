# Dynamic Position Sizing and Risk Control

Time: 2026-05-05 10:45
Goal: Dynamic position sizing + risk-adjusted trading for memecoin monitor

## Changes Applied

### Constants
- RISK_PCT: 1% -> 2% (standard level)
- MAX_BUY_SIZE:  -> 
- RISK_TIERS: automatic reduction on daily loss
  - daily loss > 2% -> reduce to 1.5%
  - daily loss > 3.5% -> reduce to 1%
- MAX_DAILY_LOSS_PCT: 5% (stop trading)
- MAX_MONTHLY_LOSS_PCT: 10% (pause 1 week)

### New Functions
1. get_effective_risk(state): Calculates daily realized + unrealized PnL percentage, returns adjusted risk factor
2. calc_buy_size(state): Uses effective risk to determine position size = account_total x effective_risk / 8%
3. check_risk_limits(state): Daily/monthly loss enforcement with pause_until persistence

### Key Design
- Start aggressive (2% risk), auto-shrink on losses
- Position = (USDT + position_value) x 2% / 8% = 25% of account (capped -)
- Example:  account -> .5 buy,  account ->  (capped)
- At -2% daily: risk drops to 1.5%, smaller positions
- At -3.5% daily: risk drops to 1%, conservative
- At -5% daily: stop trading entirely

### Files Modified
- scripts/active/realtime_sm_monitor.py (48 lines added)
- scripts/simulation/sm_monitor_sim.py (48 lines added)
- Both: syntax PASS, committed 2d5446f, pushed to GitHub