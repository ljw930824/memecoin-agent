"""Read-only local dashboard server for the dry-run monitor.

The API reads the monitor's JSON state, runtime heartbeat, and log file on
each request. Its configuration endpoint only queues validated local runtime
configuration commands; it does not write trading positions or place orders.
It binds to localhost by default.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
STATIC = Path(__file__).resolve().parent
STATE_FILE = DATA / "sm_monitor_state_dryrun.json"
RUNTIME_FILE = DATA / "dashboard_status.json"
LOG_FILE = DATA / "sm_trade-log_dryrun.txt"
CMD_FILE = DATA / "sm_commands.json"


CONFIG_LIMITS = {
    "min_mcap": (1000, 1_000_000_000),
    "max_positions": (1, 50),
    "min_consensus_wallets": (1, 100),
    "min_wallet_winrate": (0.0, 1.0),
    "buy_size_usdt": (0.10, 10_000.0),
    "min_buy_size": (0.10, 10_000.0),
    "max_buy_size": (0.10, 10_000.0),
    "risk_pct": (0.001, 0.10),
    "stop_loss_pct": (0.005, 0.50),
    "daily_loss_limit_pct": (0.01, 1.0),
    "monthly_loss_limit_pct": (0.01, 1.0),
    "quick_tp_pct": (0.001, 10.0),
    "quick_tp_sell_pct": (0.01, 1.0),
    "max_hold_hours": (0.1, 720.0),
    "poll_sec": (1.0, 300.0),
}
CONFIG_INTEGER_FIELDS = {"min_mcap", "max_positions", "min_consensus_wallets"}
CHAIN_NAMES = ("solana", "bsc", "robinhood")
CHAIN_CONFIG_KEYS = {
    "min_mcap", "max_positions", "min_consensus_wallets", "min_wallet_winrate",
    "buy_size_usdt", "min_buy_size", "max_buy_size", "risk_pct",
    "stop_loss_pct", "quick_tp_pct", "quick_tp_sell_pct", "max_hold_hours",
    "fast_exit_mode",
}
CHAIN_CONFIG_LIMITS = {
    key: CONFIG_LIMITS[key]
    for key in CHAIN_CONFIG_KEYS
    if key in CONFIG_LIMITS
}


def normalize_config_updates(updates, limits=None):
    if not isinstance(updates, dict) or not updates:
        raise ValueError("updates must be a non-empty object")
    limits = limits or CONFIG_LIMITS
    normalized = {}
    for key, value in updates.items():
        if key == "fast_exit_mode":
            if not isinstance(value, bool):
                raise ValueError("fast_exit_mode must be boolean")
            normalized[key] = value
            continue
        if key not in limits:
            raise ValueError(f"unsupported config: {key}")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be numeric")
        if not math.isfinite(number):
            raise ValueError(f"{key} must be finite")
        lower, upper = limits[key]
        if number < lower or number > upper:
            raise ValueError(f"{key} must be between {lower} and {upper}")
        if key in CONFIG_INTEGER_FIELDS:
            if not number.is_integer():
                raise ValueError(f"{key} must be an integer")
            normalized[key] = int(number)
        else:
            normalized[key] = number
    if normalized.get("min_buy_size", 0) > normalized.get("max_buy_size", float("inf")):
        raise ValueError("min_buy_size cannot exceed max_buy_size")
    return normalized


def queue_config_update(updates, chain=None):
    chain = str(chain or "").strip().lower() or None
    if chain and chain not in CHAIN_NAMES:
        raise ValueError(f"unsupported chain: {chain}")
    normalized = normalize_config_updates(updates, CHAIN_CONFIG_LIMITS if chain else CONFIG_LIMITS)
    current_runtime = read_json(RUNTIME_FILE, {})
    runtime_config = current_runtime.get("config", {}) if isinstance(current_runtime, dict) else {}
    current_config = (
        runtime_config.get("chains", {}).get(chain, {})
        if chain and isinstance(runtime_config.get("chains"), dict)
        else runtime_config
    )
    candidate = dict(current_config) if isinstance(current_config, dict) else {}
    candidate.update(normalized)
    if candidate.get("min_buy_size", 0) > candidate.get("max_buy_size", float("inf")):
        raise ValueError("min_buy_size cannot exceed max_buy_size")
    if not candidate.get("min_buy_size", 0) <= candidate.get("buy_size_usdt", 0) <= candidate.get("max_buy_size", float("inf")):
        raise ValueError("buy_size_usdt must be between min_buy_size and max_buy_size")
    commands = read_json(CMD_FILE, [])
    if not isinstance(commands, list):
        commands = []
    commands.append({
        "action": "set_config",
        "updates": normalized,
        "chain": chain,
        "source": "dashboard",
        "queued_ts": time.time(),
    })
    DATA.mkdir(parents=True, exist_ok=True)
    tmp_path = CMD_FILE.with_suffix(CMD_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(commands, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CMD_FILE)
    return normalized
HK_TZ = timezone(timedelta(hours=8))


def read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def fmt_time(value):
    try:
        ts = float(value or 0)
        if ts > 10_000_000_000:
            ts /= 1000
        if ts <= 0:
            return "--"
        return datetime.fromtimestamp(ts, HK_TZ).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "--"


def to_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def process_alive(pid):
    try:
        pid = int(pid or 0)
        if pid <= 0:
            return False
        if os.name == "nt":
            # Do not use os.kill(pid, 0) on Windows: its Windows mapping may
            # terminate the target process instead of probing it.
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError, PermissionError, SystemError):
        return False


def read_log_tail(limit=80):
    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.readlines()[-limit:]
    except OSError:
        return []


def current_runtime():
    runtime = read_json(RUNTIME_FILE, {})
    now = time.time()
    updated_ts = to_float(runtime.get("updated_ts"))
    alive = process_alive(runtime.get("pid"))
    fresh = updated_ts > 0 and now - updated_ts <= 30
    # On Windows, a sandboxed Python process may reject os.kill(pid, 0) even
    # while it is healthy. The monitor heartbeat is the authoritative signal;
    # PID liveness remains supplemental.
    if fresh and runtime.get("status") == "running":
        process_status = "running"
    elif fresh and runtime.get("status") in ("starting", "error"):
        process_status = runtime.get("status")
    elif runtime.get("status") == "running":
        process_status = "stale"
    else:
        process_status = "stopped"
    runtime["process_status"] = process_status
    runtime["heartbeat_age_sec"] = round(max(0.0, now - updated_ts), 1) if updated_ts else None
    runtime["pid_alive"] = alive
    return runtime


def build_status():
    state = read_json(STATE_FILE, {})
    runtime = current_runtime()
    positions_raw = state.get("positions") or {}
    if not isinstance(positions_raw, dict):
        positions_raw = {}
    history = state.get("trade_history") or []
    if not isinstance(history, list):
        history = []

    now = time.time()
    today = datetime.now(HK_TZ).date()
    closed_pnl = 0.0
    wins = 0
    today_closed_pnl = 0.0
    for trade in history:
        entry_usd = to_float(trade.get("entry_usd_amount"))
        exit_usd = trade.get("exit_usd")
        if exit_usd is None:
            pnl = entry_usd * to_float(trade.get("exit_pnl_pct"))
        else:
            pnl = to_float(exit_usd) - entry_usd
        closed_pnl += pnl
        if to_float(trade.get("exit_pnl_pct")) > 0:
            wins += 1
        exit_ts = to_float(trade.get("exit_ts"))
        try:
            if exit_ts and datetime.fromtimestamp(exit_ts, HK_TZ).date() == today:
                today_closed_pnl += pnl
        except (OSError, OverflowError, ValueError):
            pass

    positions = []
    open_pnl = 0.0
    for key, position in positions_raw.items():
        if not isinstance(position, dict):
            continue
        entry_price = to_float(position.get("entry_price"))
        current_price = to_float(position.get("current_price"), entry_price)
        pnl_pct = to_float(position.get("pnl_pct"))
        if not position.get("pnl_pct") and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price
        entry_usd = to_float(position.get("entry_usd_amount"), 0.0)
        open_pnl += entry_usd * pnl_pct
        entry_ts = to_float(position.get("entry_ts"))
        hold_hours = max(0.0, (now - entry_ts) / 3600) if entry_ts else 0.0
        positions.append({
            "token_ca": str(position.get("token_ca") or key),
            "symbol": position.get("symbol") or "?",
            "chain": position.get("chain") or "?",
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl_pct": pnl_pct,
            "entry_usd_amount": entry_usd,
            "hold_hours": hold_hours,
            "sm_sells": int(to_float(position.get("sm_sells"))),
            "entry_time": fmt_time(entry_ts),
            "status": "持仓中",
        })
    positions.sort(key=lambda item: item["pnl_pct"], reverse=True)

    recent = []
    for trade in sorted(history, key=lambda item: to_float(item.get("exit_ts")), reverse=True)[:12]:
        recent.append({
            "symbol": trade.get("symbol") or "?",
            "chain": trade.get("chain") or "?",
            "pnl_pct": to_float(trade.get("exit_pnl_pct")),
            "pnl_usd": to_float(trade.get("exit_usd")) - to_float(trade.get("entry_usd_amount")),
            "reason": trade.get("reason") or "--",
            "exit_time": fmt_time(trade.get("exit_ts")),
        })

    last_poll = to_float(state.get("last_poll"))
    state_age = max(0.0, now - last_poll) if last_poll else None
    risk_blocked = bool(state.get("risk_blocked"))
    risk_reason = state.get("risk_block_reason") or ("风险限制" if risk_blocked else "正常")
    runtime_config = runtime.get("config") if isinstance(runtime.get("config"), dict) else {}
    fast_exit = bool(runtime_config.get("fast_exit_mode", os.environ.get("FAST_EXIT_MODE", "1").lower() not in ("0", "false", "no")))
    quick_tp = to_float(runtime_config.get("quick_tp_pct", os.environ.get("QUICK_TP_PCT", "0.10")), 0.10)

    log_lines = [line.rstrip("\r\n") for line in read_log_tail()]
    last_log = log_lines[-1] if log_lines else "暂无模拟盘日志"
    ws_ready = bool(runtime.get("ws_ready"))
    ws_authenticated = bool(runtime.get("ws_authenticated"))
    ws_errors = runtime.get("ws_subscription_errors") or []
    rest_primary = bool(runtime.get("rest_primary"))
    rest_signal_ok = runtime.get("rest_last_signal_ok")
    rest_price_ok = runtime.get("rest_last_price_ok")
    if rest_primary and rest_signal_ok is False:
        feed_status = "OKX V6 REST 信号失败，OnchainOS 兜底"
        feed_class = "warn"
    elif rest_primary and rest_price_ok is False:
        feed_status = "OKX V6 REST 信号正常，价格接口失败"
        feed_class = "warn"
    elif rest_primary and rest_signal_ok is True:
        feed_status = "OKX V6 REST 信号/价格轮询中"
        feed_class = "ok"
    elif ws_ready:
        feed_status = "WS V6 信号订阅中"
        feed_class = "ok"
    elif ws_authenticated:
        feed_status = "WS V6 已登录，信号频道未就绪，REST 兜底"
        feed_class = "warn"
    elif runtime.get("process_status") in ("running", "starting"):
        feed_status = "REST 兜底（WS 未就绪）"
        feed_class = "warn"
    elif runtime.get("process_status") == "stale":
        feed_status = "心跳过期，检查外部 CLI"
        feed_class = "bad"
    else:
        feed_status = "未运行"
        feed_class = "bad"

    return {
        "generated_at": datetime.now(HK_TZ).isoformat(),
        "mode": "DRY-RUN",
        "runtime": runtime,
        "feed": {
            "status": feed_status,
            "class": feed_class,
            "ws_authenticated": ws_authenticated,
            "subscribed_channels": runtime.get("ws_subscribed_channels") or [],
            "subscription_errors": ws_errors[-5:],
            "rest_primary": rest_primary,
            "rest_mode": runtime.get("rest_mode", ""),
            "rest_last_signal_ok": rest_signal_ok,
            "rest_last_signal_error": runtime.get("rest_last_signal_error", ""),
            "rest_last_signal_count": runtime.get("rest_last_signal_count", 0),
            "rest_last_signal_raw_count": runtime.get("rest_last_signal_raw_count", 0),
            "rest_last_signal_counts_by_chain": runtime.get("rest_last_signal_counts_by_chain", {}),
            "rest_last_signal_raw_counts_by_chain": runtime.get("rest_last_signal_raw_counts_by_chain", {}),
            "rest_last_price_ok": rest_price_ok,
            "rest_last_price_error": runtime.get("rest_last_price_error", ""),
            "rest_last_price_count": runtime.get("rest_last_price_count", 0),
            "rest_last_price_counts_by_chain": runtime.get("rest_last_price_counts_by_chain", {}),
            "rest_request_count": runtime.get("rest_request_count", 0),
            "rest_chain_indexes": runtime.get("rest_chain_indexes") or [],
            "bsc_market_data_source": runtime.get("bsc_market_data_source", ""),
            "bsc_baw_enabled": bool(runtime.get("bsc_baw_enabled")),
        },
        "risk": {"blocked": risk_blocked, "reason": risk_reason},
        "config": {
            "min_mcap": int(to_float(runtime_config.get("min_mcap"), 30000)),
            "max_positions": int(to_float(runtime_config.get("max_positions"), 3)),
            "min_consensus_wallets": int(to_float(runtime_config.get("min_consensus_wallets"), 1)),
            "min_wallet_winrate": to_float(runtime_config.get("min_wallet_winrate"), 0.50),
            "buy_size_usdt": to_float(runtime_config.get("buy_size_usdt"), 5),
            "min_buy_size": to_float(runtime_config.get("min_buy_size"), 3),
            "max_buy_size": to_float(runtime_config.get("max_buy_size"), 15),
            "risk_pct": to_float(runtime_config.get("risk_pct"), 0.02),
            "stop_loss_pct": to_float(runtime_config.get("stop_loss_pct"), 0.08),
            "daily_loss_limit_pct": to_float(runtime_config.get("daily_loss_limit_pct"), 0.05),
            "monthly_loss_limit_pct": to_float(runtime_config.get("monthly_loss_limit_pct"), 0.10),
            "quick_tp_pct": quick_tp,
            "quick_tp_sell_pct": to_float(runtime_config.get("quick_tp_sell_pct"), 1.0),
            "fast_exit_mode": fast_exit,
            "max_hold_hours": to_float(runtime_config.get("max_hold_hours"), 2),
            "poll_sec": to_float(runtime_config.get("poll_sec"), 10),
            "bsc_baw_enabled": bool(runtime_config.get("bsc_baw_enabled", runtime.get("bsc_baw_enabled"))),
            "chains": runtime_config.get("chains", {}),
        },
        "metrics": {
            "open_positions": len(positions),
            "closed_trades": len(history),
            "win_rate": wins / len(history) if history else None,
            "closed_pnl_usd": closed_pnl,
            "open_pnl_usd": open_pnl,
            "today_pnl_usd": today_closed_pnl,
            "signals_pending": len(state.get("buy_signals") or []),
            "wallets_tracked": None,
            "state_age_sec": round(state_age, 1) if state_age is not None else None,
        },
        "positions": positions,
        "recent_trades": recent,
        "logs": log_lines,
        "last_log": last_log,
        "source": {
            "state_file": str(STATE_FILE),
            "runtime_file": str(RUNTIME_FILE),
            "log_file": str(LOG_FILE),
        },
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/status":
            body = json.dumps(build_status(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path in ("/", "/index.html"):
            try:
                self._send(200, "text/html; charset=utf-8", (STATIC / "index.html").read_bytes())
            except OSError:
                self._send(404, "text/plain; charset=utf-8", "dashboard not found")
            return
        self._send(404, "text/plain; charset=utf-8", "not found")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/config":
            self._send(404, "text/plain; charset=utf-8", "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("request body is missing or too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            updates = payload.get("updates", payload) if isinstance(payload, dict) else None
            chain = payload.get("chain") if isinstance(payload, dict) else None
            normalized = queue_config_update(updates, chain=chain)
            body = json.dumps({
                "ok": True,
                "queued": True,
                "chain": chain,
                "updates": normalized,
                "message": "配置已提交，将在模拟盘下一轮轮询时生效",
            }, ensure_ascii=False).encode("utf-8")
            self._send(202, "application/json; charset=utf-8", body)
        except (ValueError, TypeError, json.JSONDecodeError, OSError) as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self._send(400, "application/json; charset=utf-8", body)

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Local dry-run dashboard with validated runtime config")
    parser.add_argument("--host", default=os.environ.get("DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", "8765")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard listening on http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
