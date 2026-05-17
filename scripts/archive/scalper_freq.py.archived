#!/usr/bin/env python3
"""
Scalper v3.3+ - Dynamic Frequency Manager
根据持仓状态自动调整扫描频率 + pageSize

逻辑：
- 无持仓 or 资金闲置  → 高频扫信号 (12min) + 大范围 (pageSize=20)
- 有持仓 + P&L > +5%  → 中频扫信号 (20min) + 中范围 (pageSize=10)
- 有持仓 + P&L < -3%  → 低频扫信号 (45min) + 小范围 (pageSize=5) 专注持仓
- 持仓扫描 始终优先于 信号扫描
"""

import json, os, sys, time
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR   = os.path.expanduser("~/.qclaw/workspace/data")
FREQ_CTRL  = os.path.join(DATA_DIR, "frequency-ctrl.json")
os.makedirs(DATA_DIR, exist_ok=True)

# === 动态频率表 ===
IDLE_CONFIG   = {"interval_min": 12, "pageSize": 20}   # 无持仓
WARM_CONFIG   = {"interval_min": 20, "pageSize": 10}   # 持仓盈利
CRITICAL_CONFIG = {"interval_min": 45, "pageSize": 5}  # 持仓亏损/专注持仓


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "cooldowns": {}, "signal_scores": {}}


def load_freq_ctrl():
    if os.path.exists(FREQ_CTRL):
        with open(FREQ_CTRL, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_freq_ctrl(data):
    with open(FREQ_CTRL, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_dynamic_config(state):
    """根据持仓状态返回当前频率配置"""
    positions = state.get("positions", {})
    open_count = len(positions)

    if open_count == 0:
        return IDLE_CONFIG.copy(), "IDLE"

    # 计算整体 P&L
    total_pnl_pct = 0
    for pos in positions.values():
        ep = float(pos.get("entry_price", 0))
        cp = float(pos.get("current_price", ep))
        if ep > 0:
            total_pnl_pct += (cp - ep) / ep
    avg_pnl = total_pnl_pct / open_count if open_count > 0 else 0

    if avg_pnl > 0.05:
        return WARM_CONFIG.copy(), f"WARM(+{avg_pnl*100:.1f}%)"
    elif avg_pnl < -0.03:
        return CRITICAL_CONFIG.copy(), f"CRITICAL({avg_pnl*100:.1f}%)"
    else:
        return WARM_CONFIG.copy(), f"WARM({avg_pnl*100:.1f}%)"


def should_run_signals(freq_ctrl, config, now_ts):
    """检查信号扫描是否应该执行"""
    last = freq_ctrl.get("last_signal_scan", 0)
    interval_ms = config["interval_min"] * 60 * 1000
    elapsed = now_ts * 1000 - last
    return last == 0 or elapsed >= interval_ms


def should_run_positions(freq_ctrl, config, now_ts):
    """检查持仓扫描是否应该执行（优先于信号扫描）"""
    last = freq_ctrl.get("last_position_scan", 0)
    # 持仓扫描始终比信号扫描更频繁（60% 权重）
    interval_ms = config["interval_min"] * 60 * 1000 * 0.6
    elapsed = now_ts * 1000 - last
    return last == 0 or elapsed >= interval_ms


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_ts = now.timestamp()

    state = load_state()
    freq_ctrl = load_freq_ctrl()

    config, mode = get_dynamic_config(state)
    interval = config["interval_min"]
    page_size = config["pageSize"]

    # 检查信号扫描时间
    do_signals = should_run_signals(freq_ctrl, config, now_ts)

    # 检查持仓扫描时间（始终每 interval*0.6 min 执行一次）
    do_positions = should_run_positions(freq_ctrl, config, now_ts)

    if not do_signals and not do_positions:
        # 不需要运行，更新下次提醒时间
        next_signal = freq_ctrl.get("last_signal_scan", 0) + interval * 60000
        next_pos = freq_ctrl.get("last_position_scan", 0) + int(interval * 0.6 * 60000)
        wait_s = min(next_signal, next_pos) / 1000 - now_ts
        print(f"[FREQ CTRL] Mode={mode} | signal in {wait_s/60:.0f}min | pos in {wait_s*0.6/60:.0f}min | SKIP")
        save_freq_ctrl(freq_ctrl)
        return

    # 更新扫描记录
    if do_signals:
        freq_ctrl["last_signal_scan"] = now_ts * 1000
    if do_positions:
        freq_ctrl["last_position_scan"] = now_ts * 1000

    save_freq_ctrl(freq_ctrl)

    # 输出当前配置
    print(f"\n{'='*50}")
    print(f"FREQ MANAGER | {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {mode} | interval={interval}min | pageSize={page_size}")
    print(f"Signals: {'RUN' if do_signals else 'skip'} | Positions: {'RUN' if do_positions else 'skip'}")
    print(f"{'='*50}")

    # 执行信号扫描
    if do_signals:
        print(f"\n>> Running signal scan (pageSize={page_size})...")
        exit_code = os.system('python "{}" {}'.format(
            os.path.join(DATA_DIR.replace("data", "scripts"), "scalper_signals.py"),
            f"--pageSize={page_size}"))
        if exit_code != 0:
            print(f"[WARN] signals exit code: {exit_code}")

    # 执行持仓扫描
    if do_positions:
        print(f"\n>> Running position scan...")
        exit_code = os.system('python "{}"'.format(
            os.path.join(DATA_DIR.replace("data", "scripts"), "scalper_positions.py")))
        if exit_code != 0:
            print(f"[WARN] positions exit code: {exit_code}")

    print(f"\n[DONE] next signal: ~{interval}min | next pos: ~{int(interval*0.6)}min")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()