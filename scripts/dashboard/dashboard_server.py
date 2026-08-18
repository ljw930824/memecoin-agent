"""Read-only local dashboard server for the dry-run monitor.

The API reads the monitor's JSON state, runtime heartbeat, and log file on
each request. It does not write trading state and it binds to localhost by
default.
"""
from __future__ import annotations

import argparse
import json
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
    fast_exit = os.environ.get("FAST_EXIT_MODE", "1").lower() not in ("0", "false", "no")
    quick_tp = to_float(os.environ.get("QUICK_TP_PCT", "0.10"), 0.10)

    log_lines = [line.rstrip("\r\n") for line in read_log_tail()]
    last_log = log_lines[-1] if log_lines else "暂无模拟盘日志"
    ws_ready = bool(runtime.get("ws_ready"))
    ws_authenticated = bool(runtime.get("ws_authenticated"))
    ws_errors = runtime.get("ws_subscription_errors") or []
    if ws_ready:
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
        },
        "risk": {"blocked": risk_blocked, "reason": risk_reason},
        "config": {
            "max_positions": 3,
            "buy_size_usdt": 5,
            "quick_tp_pct": quick_tp,
            "fast_exit_mode": fast_exit,
            "stop_loss_pct": -0.08,
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

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Local read-only dry-run dashboard")
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
