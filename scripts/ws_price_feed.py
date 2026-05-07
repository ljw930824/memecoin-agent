"""
OKX WebSocket Module - Real-time price feed for monitor.
Direct connection to OKX WS API, no OnChainOS CLI dependency.
Supports: CEX prices (SOL, BNB, ETH, BTC), DEX price polling via REST.
"""
import websocket
import json
import threading
import time
import os
import logging
from collections import defaultdict
from datetime import datetime

log = logging.getLogger("okx_ws")

# ── Config ──────────────────────────────────────────────────────────────
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
HEARTBEAT_INTERVAL = 25  # seconds (OKX requires ping every 30s)
RECONNECT_DELAY = 5
MAX_RECONNECTS = 10

# ── Price Store (thread-safe) ───────────────────────────────────────────
class PriceStore:
    """Thread-safe in-memory price store."""
    def __init__(self):
        self._lock = threading.Lock()
        self._prices = {}  # instId -> {px, ts, side}
        self._callbacks = []

    def update(self, inst_id: str, px: float, side: str, ts: int):
        with self._lock:
            self._prices[inst_id] = {
                'px': px, 'side': side, 'ts': ts,
                'updated': time.time()
            }
        for cb in self._callbacks:
            try:
                cb(inst_id, px, side, ts)
            except Exception as e:
                log.warning(f"callback error: {e}")

    def get(self, inst_id: str):
        with self._lock:
            return self._prices.get(inst_id)

    def get_all(self):
        with self._lock:
            return dict(self._prices)

    def on_update(self, callback):
        self._callbacks.append(callback)

    def age(self, inst_id: str):
        """Return age in seconds since last update."""
        with self._lock:
            entry = self._prices.get(inst_id)
            if entry:
                return time.time() - entry['updated']
        return float('inf')

price_store = PriceStore()

# ── WS Manager ──────────────────────────────────────────────────────────
class OKXWebSocket:
    def __init__(self, channels=None):
        self.channels = channels or [
            "SOL-USDT", "BNB-USDT", "ETH-USDT", "BTC-USDT"
        ]
        self.ws = None
        self._thread = None
        self._running = False
        self._reconnect_count = 0
        self._last_heartbeat = 0

    def _on_open(self, ws):
        log.info("WS connected")
        self._reconnect_count = 0
        # Subscribe to all channels
        for inst_id in self.channels:
            sub = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": inst_id}]
            }
            ws.send(json.dumps(sub))
            log.debug(f"Subscribed: {inst_id}")

    def _on_message(self, ws, msg):
        # Handle pong / non-JSON messages
        if not msg or msg == 'pong' or msg[0] not in '{[':
            return
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return
        if 'data' in data:
            for item in data['data']:
                inst = item.get('instId', '')
                px = float(item.get('last', 0))
                side = 'buy' if float(item.get('lastSz', 0)) > 0 else 'sell'
                ts = int(item.get('ts', 0))
                if px > 0:
                    price_store.update(inst, px, side, ts)
        elif data.get('event') == 'subscribe':
            log.debug(f"Subscribed OK: {data.get('arg', {})}")
        elif data.get('event') == 'error':
            log.error(f"WS error: {data}")

    def _on_error(self, ws, err):
        log.error(f"WS error: {err}")

    def _on_close(self, ws, code, reason):
        log.warning(f"WS closed: {code} - {reason}")
        if self._running:
            self._reconnect()

    def _heartbeat(self):
        """Send ping every HEARTBEAT_INTERVAL seconds."""
        while self._running:
            time.sleep(1)
            if self.ws and time.time() - self._last_heartbeat > HEARTBEAT_INTERVAL:
                try:
                    self.ws.send("ping")
                    self._last_heartbeat = time.time()
                except:
                    pass

    def _reconnect(self):
        if self._reconnect_count >= MAX_RECONNECTS:
            log.error(f"Max reconnects ({MAX_RECONNECTS}) reached, stopping")
            self._running = False
            return
        self._reconnect_count += 1
        delay = RECONNECT_DELAY * self._reconnect_count
        log.info(f"Reconnecting in {delay}s (attempt {self._reconnect_count})")
        time.sleep(delay)
        self._connect()

    def _connect(self):
        self.ws = websocket.WebSocketApp(
            OKX_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def start(self):
        """Start WS in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        # Start heartbeat
        hb = threading.Thread(target=self._heartbeat, daemon=True)
        hb.start()
        log.info("WS started in background")

    def stop(self):
        self._running = False
        if self.ws:
            self.ws.close()

# ── DEX Price Polling (via OnChainOS REST) ──────────────────────────────
class DEXPricePoller:
    """
    Polls DEX token prices via onchainos CLI.
    Runs in background thread, updates price_store.
    """
    def __init__(self, interval=5):
        self.interval = interval
        self._tokens = {}  # ca -> {chain, last_price}
        self._thread = None
        self._running = False

    def track(self, ca: str, chain: str = "solana"):
        """Add a token to price polling."""
        self._tokens[ca] = {'chain': chain, 'last_price': 0}

    def untrack(self, ca: str):
        self._tokens.pop(ca, None)

    def _poll_loop(self):
        import subprocess
        while self._running:
            for ca, info in list(self._tokens.items()):
                try:
                    r = subprocess.run(
                        ['onchainos', 'token', 'price-info',
                         '--address', ca, '--chain', info['chain']],
                        capture_output=True, timeout=8,
                        encoding='utf-8', errors='replace'
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        data = json.loads(r.stdout.strip())
                        px = float(data.get('priceUsd', 0))
                        if px > 0:
                            inst = f"DEX:{ca[:8]}"
                            price_store.update(inst, px, 'buy', int(time.time()*1000))
                            self._tokens[ca]['last_price'] = px
                except Exception as e:
                    log.debug(f"DEX poll error {ca[:8]}: {e}")
            time.sleep(self.interval)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

# ── Global instances ────────────────────────────────────────────────────
cex_ws = OKXWebSocket()
dex_poller = DEXPricePoller()

def get_price(inst_id: str):
    """Get latest price. inst_id can be 'SOL-USDT' or 'DEX:<ca_prefix>'"""
    entry = price_store.get(inst_id)
    return entry['px'] if entry else None

def get_price_fresh(inst_id: str, max_age_sec=30):
    """Get price only if fresh (within max_age_sec)."""
    if price_store.age(inst_id) < max_age_sec:
        entry = price_store.get(inst_id)
        return entry['px'] if entry else None
    return None

def start_all():
    """Start both CEX WS and DEX poller."""
    cex_ws.start()
    dex_poller.start()
    log.info("All price feeds started")

def stop_all():
    cex_ws.stop()
    dex_poller.stop()

# ── CLI test ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    start_all()
    try:
        while True:
            time.sleep(5)
            all_p = price_store.get_all()
            for inst, data in sorted(all_p.items()):
                age = price_store.age(inst)
                print(f"  {inst}: ${data['px']:,.2f} ({age:.0f}s ago)")
    except KeyboardInterrupt:
        stop_all()
