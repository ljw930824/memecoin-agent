"""
api_health_check.py - API 连通性健康检查 + 信号队列新鲜度 + 连续失败升级告警
每5分钟由 Task Scheduler 调用
"""
import json
import os
import subprocess
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from qclaw_trading_common import (  # noqa: E402
    locked_read_json,
    locked_write_json,
    okx_env_for_subprocess,
    telegram_env,
)

DATA_DIR = os.path.join(os.path.expanduser("~"), ".qclaw", "workspace", "data")
HEALTH_LOG = os.path.join(DATA_DIR, "api-health.log")
ALERT_LOG = os.path.join(DATA_DIR, "api-alerts.log")
HEALTH_STATE = os.path.join(DATA_DIR, "health-check-state.json")
QUEUE_FILE = os.path.join(DATA_DIR, "signal-queue.json")
STATE_FILE = os.path.join(DATA_DIR, "smart-money-state.json")
RECONCILE_LOG = os.path.join(DATA_DIR, "reconcile-hints.log")
os.makedirs(DATA_DIR, exist_ok=True)

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"

now = datetime.now(timezone(timedelta(hours=8)))
ts = now.strftime("%Y-%m-%d %H:%M")
results = {}

ALERT_STREAK_THRESHOLD = int(os.environ.get("HEALTH_ALERT_STREAK", "2"))
QUEUE_MAX_AGE_SEC = float(os.environ.get("SIGNAL_QUEUE_MAX_AGE_SEC", "180"))


def _notify_telegram(msg: str) -> None:
    tok, chat = telegram_env()
    if not tok or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{tok}/sendMessage"
        data = json.dumps({"chat_id": chat, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=12):
            pass
    except Exception as ex:
        print(f"  [WARN] telegram notify failed: {str(ex)[:120]}")


def check_binance_api():
    try:
        ssl_ctx = ssl.create_default_context()
        url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
        body = json.dumps({"smartSignalType": "", "page": 1, "pageSize": 5, "chainId": "56"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            d = json.loads(r.read().decode("utf-8"))
            code = d.get("code", "")
            items = d.get("data", []) if isinstance(d.get("data"), list) else []
            if code == "000000" or d.get("ok"):
                return True, f"{len(items)} signals"
            return False, f"code={code}"
    except Exception as e:
        return False, str(e)[:80]


def check_onchainos():
    env = okx_env_for_subprocess()
    if not env:
        return False, "missing_OKX_env"
    try:
        r = subprocess.run(
            ["onchainos", "signal", "list", "--chain", "solana", "--limit", "3"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            env=env,
        )
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                count = len(d.get("data", []))
                return True, f"{count} signals"
            except json.JSONDecodeError:
                return True, "response OK (non-JSON)"
        return False, r.stderr[:80] if r.stderr else f"exit={r.returncode}"
    except Exception as e:
        return False, str(e)[:80]


def check_tracker():
    """Smart-money tracker (fast path) — same credentials as onchainos."""
    env = okx_env_for_subprocess()
    if not env:
        return False, "missing_OKX_env"
    try:
        r = subprocess.run(
            [
                "onchainos",
                "tracker",
                "activities",
                "--tracker-type",
                "smart_money",
                "--chain",
                "solana",
                "--min-volume",
                "400",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            env=env,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "")[:80]
        return True, "tracker_ok"
    except Exception as e:
        return False, str(e)[:80]


def check_baw():
    try:
        r = subprocess.run(
            [BAW_CMD, "wallet", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
        )
        if r.returncode == 0 and "Logged in" in r.stdout:
            return True, "Logged in"
        return False, r.stdout[:80] if r.stdout else f"exit={r.returncode}"
    except Exception as e:
        return False, str(e)[:80]


def check_signal_queue():
    """signal-queue.json mtime + newest entry ts (written by signal_fetch_once)."""
    if not os.path.isfile(QUEUE_FILE):
        return False, "queue_missing"
    try:
        age = time.time() - os.path.getmtime(QUEUE_FILE)
        if age > QUEUE_MAX_AGE_SEC:
            return False, f"queue_mtime_stale={age:.0f}s"
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return False, "queue_not_list"
        newest = 0.0
        for s in data:
            if isinstance(s, dict):
                newest = max(newest, float(s.get("ts", 0) or 0))
        if newest <= 0:
            return True, f"ok mtime_age={age:.0f}s (no ts in items)"
        sig_age = time.time() - newest
        if sig_age > 7200:
            return False, f"newest_signal_ts_age={sig_age:.0f}s"
        return True, f"ok mtime={age:.0f}s sig_ts={sig_age:.0f}s"
    except Exception as e:
        return False, str(e)[:60]


def check_state_reconcile_hint():
    """Lightweight hint: state exists but queue empty — log once per run."""
    try:
        if not os.path.isfile(STATE_FILE):
            return True, "no_state"
        st = locked_read_json(STATE_FILE, {})
        npos = len(st.get("positions") or {})
        if npos == 0:
            return True, "no_positions"
        if os.path.isfile(QUEUE_FILE):
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                q = json.load(f)
            if isinstance(q, list) and len(q) == 0 and npos > 0:
                line = f"[{ts}] hint: {npos} positions but empty queue\n"
                with open(RECONCILE_LOG, "a", encoding="utf-8") as rf:
                    rf.write(line)
                return True, "empty_queue_hint_logged"
        return True, f"positions={npos}"
    except Exception as e:
        return False, str(e)[:50]


checks = [
    ("binance_api", check_binance_api),
    ("onchainos", check_onchainos),
    ("tracker", check_tracker),
    ("baw", check_baw),
    ("signal_queue", check_signal_queue),
    ("reconcile_hint", check_state_reconcile_hint),
]

for name, fn in checks:
    ok, detail = fn()
    results[name] = {"ok": ok, "detail": detail}
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail}")

all_ok = all(r["ok"] for r in results.values())
log_line = (
    f'[{ts}] {"ALL_OK" if all_ok else "ISSUE"} | '
    + " | ".join(f'{k}={v["detail"]}' for k, v in results.items())
)
with open(HEALTH_LOG, "a", encoding="utf-8") as f:
    f.write(log_line + "\n")

# Streak + Telegram escalation
h = locked_read_json(HEALTH_STATE, {"streak": {}, "last_telegram_ts": 0})
streak = h.setdefault("streak", {})
any_fail = False
for name, r in results.items():
    if r["ok"]:
        streak[name] = 0
    else:
        streak[name] = streak.get(name, 0) + 1
        any_fail = True

h["streak"] = streak
locked_write_json(HEALTH_STATE, h)

if not all_ok:
    failed = [f"{k}: {v['detail']}" for k, v in results.items() if not v["ok"]]
    alert = f"[{ts}] API ALERT: {'; '.join(failed)}"
    print(f"  [ALERT] {alert}")
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(alert + "\n")

    hot = [k for k, v in results.items() if not v["ok"] and streak.get(k, 0) >= ALERT_STREAK_THRESHOLD]
    if hot:
        last_ts = float(h.get("last_telegram_ts", 0) or 0)
        if time.time() - last_ts > 300:
            _notify_telegram(
                "&#x26A0; <b>Health check</b> consecutive failures: "
                + ", ".join(hot)
                + "\n"
                + alert[:3500]
            )
            h2 = locked_read_json(HEALTH_STATE, {})
            h2["last_telegram_ts"] = time.time()
            locked_write_json(HEALTH_STATE, h2)
