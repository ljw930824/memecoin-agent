"""
OKX WebSocket Module - Real-time price feed for monitor.
Direct connection to OKX WS API, no OnChainOS CLI dependency.
Supports: CEX prices (SOL, BNB, ETH, BTC), DEX smart money signals.
"""
import websocket
import json
import threading
import time
import os
import logging
import hmac
import hashlib
import base64
from collections import defaultdict
from datetime import datetime

log = logging.getLogger("okx_ws")

# ── Config ──────────────────────────────────────────────────────────────
OKX_CEX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_DEX_WS_URL = "wss://wsdex.okx.com/ws/v6/dex"
HEARTBEAT_INTERVAL = 25  # seconds (OKX requires ping every 30s)
RECONNECT_DELAY = 5
MAX_RECONNECTS = 10

# ── Signal Store (thread-safe) ──────────────────────────────────────────
class SignalStore:
    """Thread-safe in-memory signal store for smart money data."""
    def __init__(self):
        self._lock = threading.Lock()
        self._signals = []  # List of signal dicts
        self._callbacks = []
        self._last_signal_ts = 0

    def add(self, signal: dict):
        """Add a new signal."""
        with self._lock:
            self._signals.append(signal)
            self._last_signal_ts = time.time()
            # Keep only last 1000 signals
            if len(self._signals) > 1000:
                self._signals = self._signals[-1000:]
        for cb in self._callbacks:
            try:
                cb(signal)
            except Exception as e:
                log.warning(f"signal callback error: {e}")

    def get_recent(self, n=10):
        """Get last n signals."""
        with self._lock:
            return self._signals[-n:]

    def get_all(self):
        """Get all signals."""
        with self._lock:
            return list(self._signals)

    def on_signal(self, callback):
        self._callbacks.append(callback)

    def last_signal_age(self):
        """Return seconds since last signal."""
        with self._lock:
            return time.time() - self._last_signal_ts

signal_store = SignalStore()

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

# ── CEX WS Manager ──────────────────────────────────────────────────────
class OKXCEXWebSocket:
    """OKX CEX WebSocket for price data (SOL, BNB, ETH, BTC)."""
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
        log.info("CEX WS connected")
        self._reconnect_count = 0
        for inst_id in self.channels:
            sub = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": inst_id}]
            }
            ws.send(json.dumps(sub))
            log.debug(f"Subscribed: {inst_id}")

    def _on_message(self, ws, msg):
        if not msg or msg == 'pong' or (msg and msg[0] not in '{['):
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
            log.error(f"CEX WS error: {data}")

    def _on_error(self, ws, err):
        log.error(f"CEX WS error: {err}")

    def _on_close(self, ws, code, reason):
        log.warning(f"CEX WS closed: {code} - {reason}")
        if self._running:
            self._reconnect()

    def _heartbeat(self):
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
            log.error(f"CEX Max reconnects ({MAX_RECONNECTS}) reached")
            self._running = False
            return
        self._reconnect_count += 1
        delay = RECONNECT_DELAY * self._reconnect_count
        log.info(f"CEX Reconnecting in {delay}s (attempt {self._reconnect_count})")
        time.sleep(delay)
        self._connect()

    def _connect(self):
        self.ws = websocket.WebSocketApp(
            OKX_CEX_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        hb = threading.Thread(target=self._heartbeat, daemon=True)
        hb.start()
        log.info("CEX WS started")

    def stop(self):
        self._running = False
        if self.ws:
            self.ws.close()

# ── DEX WS Manager (Smart Money Signals) ────────────────────────────────
class OKXDEXWebSocket:
    """OKX DEX WebSocket for smart money signals."""
    def __init__(self, api_key=None, secret=None, passphrase=None):
        self.api_key = api_key or os.environ.get("OKX_API_KEY", "")
        self.secret = secret or os.environ.get("OKX_SECRET_KEY", "")
        self.passphrase = passphrase or os.environ.get("OKX_PASSPHRASE", "")
        self.ws = None
        self._thread = None
        self._running = False
        self._reconnect_count = 0
        self._last_heartbeat = 0
        self._logged_in = False
        self._subscribed_channels = []

    def _make_auth(self):
        """Create OKX WS login message."""
        ts = str(int(time.time()))
        msg = ts + "GET" + "/users/self/verify"
        mac = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).digest()
        sign = base64.b64encode(mac).decode()
        return {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": ts,
                "sign": sign
            }]
        }

    def _on_open(self, ws):
        log.info("DEX WS connected")
        self._reconnect_count = 0
        self._logged_in = False
        # Send auth
        if self.api_key and self.secret:
            auth = self._make_auth()
            ws.send(json.dumps(auth))
            log.debug("Sent DEX auth")
        else:
            log.error("DEX WS requires API key/secret")

    def _on_message(self, ws, msg):
        if not msg or msg == 'pong' or (msg and msg[0] not in '{['):
            return
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        event = data.get('event')
        
        if event == 'login':
            self._logged_in = True
            log.info("DEX WS logged in")
            # Subscribe to smart money channels
            self._subscribe_smart_money(ws)
            
        elif event == 'error':
            log.error(f"DEX WS error: {data.get('code')} - {data.get('msg')}")
            
        elif event == 'subscribe':
            log.debug(f"DEX subscribed: {data.get('arg', {})}")
            
        elif 'data' in data:
            # Process smart money signal
            channel = data.get('arg', {}).get('channel', '')
            for item in data['data']:
                signal = {
                    'channel': channel,
                    'ts': time.time(),
                    'data': item
                }
                signal_store.add(signal)
                # Also log key info
                token = item.get('tokenSymbol', 'UNKNOWN')
                chain = item.get('chainIndex', '?')
                pnl = item.get('realizedPnlUsd', '0')
                log.info(f"Signal: {token} (chain {chain}) PnL: ${pnl}")

    def _subscribe_smart_money(self, ws):
        """Subscribe to smart money channels."""
        channels = [
            {"channel": "kol_smartmoney-tracker-activity"},
            {"channel": "dex-market-new-signal-openapi", "chainIndex": "501"},  # Solana
            {"channel": "dex-market-new-signal-openapi", "chainIndex": "56"},   # BSC
        ]
        for ch in channels:
            ws.send(json.dumps({"op": "subscribe", "args": [ch]}))
            log.debug(f"Subscribing: {ch}")

    def _on_error(self, ws, err):
        log.error(f"DEX WS error: {err}")

    def _on_close(self, ws, code, reason):
        log.warning(f"DEX WS closed: {code} - {reason}")
        self._logged_in = False
        if self._running:
            self._reconnect()

    def _heartbeat(self):
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
            log.error(f"DEX Max reconnects ({MAX_RECONNECTS}) reached")
            self._running = False
            return
        self._reconnect_count += 1
        delay = RECONNECT_DELAY * self._reconnect_count
        log.info(f"DEX Reconnecting in {delay}s (attempt {self._reconnect_count})")
        time.sleep(delay)
        self._connect()

    def _connect(self):
        self.ws = websocket.WebSocketApp(
            OKX_DEX_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def start(self):
        if self._running:
            return
        if not self.api_key or not self.secret:
            log.error("DEX WS requires OKX_API_KEY and OKX_SECRET_KEY env vars")
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        hb = threading.Thread(target=self._heartbeat, daemon=True)
        hb.start()
        log.info("DEX WS started")

    def stop(self):
        self._running = False
        if self.ws:
            self.ws.close()

    def is_logged_in(self):
        return self._logged_in

# ── Global instances ────────────────────────────────────────────────────
cex_ws = OKXCEXWebSocket()
dex_ws = OKXDEXWebSocket()

def get_price(inst_id: str):
    """Get latest CEX price. inst_id like 'SOL-USDT'."""
    entry = price_store.get(inst_id)
    return entry['px'] if entry else None

def get_price_fresh(inst_id: str, max_age_sec=30):
    """Get CEX price only if fresh (within max_age_sec)."""
    if price_store.age(inst_id) < max_age_sec:
        entry = price_store.get(inst_id)
        return entry['px'] if entry else None
    return None

def get_recent_signals(n=10):
    """Get recent smart money signals."""
    return signal_store.get_recent(n)

def start_all():
    """Start both CEX and DEX WebSockets."""
    cex_ws.start()
    dex_ws.start()
    log.info("All WebSocket feeds started")

def stop_all():
    cex_ws.stop()
    dex_ws.stop()

def status():
    """Return status of both WS connections."""
    return {
        'cex': {
            'running': cex_ws._running,
            'prices': list(price_store.get_all().keys())
        },
        'dex': {
            'running': dex_ws._running,
            'logged_in': dex_ws.is_logged_in(),
            'signals_count': len(signal_store.get_all()),
            'last_signal_age': signal_store.last_signal_age()
        }
    }

# ── CLI test ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    start_all()
    try:
        while True:
            time.sleep(10)
            print(f"\n--- Status ---")
            s = status()
            print(f"CEX: {s['cex']['running']} | Prices: {s['cex']['prices']}")
            print(f"DEX: {s['dex']['running']} | Logged in: {s['dex']['logged_in']} | Signals: {s['dex']['signals_count']}")
            
            # Show recent signals
            signals = get_recent_signals(3)
            if signals:
                print("Recent signals:")
                for sig in signals:
                    d = sig['data']
                    print(f"  {d.get('tokenSymbol')} (chain {d.get('chainIndex')}): PnL ${d.get('realizedPnlUsd', 0)}")
    except KeyboardInterrupt:
        stop_all()
        print("\nStopped.")
