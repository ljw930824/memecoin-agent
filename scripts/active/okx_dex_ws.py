"""
okx_dex_ws.py — OKX DEX WebSocket v6 直连模块
替代 onchainos ws start (被 WARP DNS 阻断) 和 REST 轮询

Usage:
    from okx_dex_ws import OkxDexWs
    ws = OkxDexWs()
    ws.start()
    # ... in loop:
    events = ws.get_events()  # returns list of normalized trade dicts
    ws.stop()

Credentials: OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE (非PROD! 别用PROD)
"""
import os
import sys
import json
import time
import threading
import queue
import logging
import hmac
import hashlib
import base64

try:
    import websocket
except ImportError:
    print("[okx_dex_ws] websocket-client 未安装，执行: pip install websocket-client")
    sys.exit(1)

logger = logging.getLogger("okx_dex_ws")

WS_URL = "wss://wsdex.okx.com/ws/v6/dex"
PING_INTERVAL = 25  # seconds
RECONNECT_DELAY = 5  # seconds
MAX_QUEUE_SIZE = 5000

# tradeType: "1"=buy, "2"=sell (same format as REST tracker, no conversion needed)


def _make_sign(secret_key: str) -> tuple:
    """HMAC-SHA256 signature per OKX DEX WS protocol."""
    ts = str(int(time.time()))
    prehash = ts + "GET/users/self/verify"
    sig = base64.b64encode(
        hmac.new(secret_key.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig


def _normalize_event(data_item: dict) -> dict:
    """Pass-through WS event to REST tracker-compatible format."""
    return {
        "chainIndex": str(data_item.get("chainIndex", "")),
        "walletAddress": data_item.get("walletAddress", ""),
        "tokenContractAddress": data_item.get("tokenContractAddress", ""),
        "tokenSymbol": data_item.get("tokenSymbol", ""),
        "marketCap": data_item.get("marketCap", ""),
        "quoteTokenAmount": data_item.get("quoteTokenAmount", ""),
        "quoteTokenSymbol": data_item.get("quoteTokenSymbol", ""),
        "tokenPrice": data_item.get("tokenPrice", ""),
        "realizedPnlUsd": data_item.get("realizedPnlUsd", "0"),
        "tradeType": str(data_item.get("tradeType", "")),  # "1"=buy, "2"=sell, same as REST
        "tradeTime": data_item.get("tradeTime", ""),
        "txHash": data_item.get("txHash", ""),
        "trackerType": data_item.get("trackerType", []),
        # Computed: blockTimestamp from tradeTime (ms→s)
        "blockTimestamp": str(int(data_item.get("tradeTime", "0")) // 1000) if data_item.get("tradeTime") else "",
    }


class OkxDexWs:
    """OKX DEX WebSocket v6 client with auto-reconnect and event buffering."""

    def __init__(self, channels=None, chain_indexes=None, wallet_addresses=None):
        """
        Args:
            channels: list of WS channel names, default ['kol_smartmoney-tracker-activity']
            chain_indexes: optional chain indexes filter (e.g. ['501', '56'])
            wallet_addresses: optional wallet addresses for address-tracker-activity
        """
        self.channels = channels or ["kol_smartmoney-tracker-activity"]
        self.chain_indexes = chain_indexes or []
        self.wallet_addresses = wallet_addresses or []

        # Credentials
        self.api_key = os.environ.get("OKX_API_KEY", "")
        self.secret = os.environ.get("OKX_SECRET_KEY", "")
        self.passphrase = os.environ.get("OKX_PASSPHRASE", "")

        # Events queue (thread-safe)
        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)

        # State
        self._ws = None
        self._thread = None
        self._running = False
        self._connected = False
        self._logged_in = False
        self._subscribed = set()
        self._event_count = 0
        self._error_count = 0
        self._last_event_ts = 0

    # ── Public API ──

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def error_count(self) -> int:
        return self._error_count

    def start(self):
        """Start WebSocket connection in background thread."""
        if self._running:
            return
        if not self.api_key:
            logger.error("OKX_API_KEY not set in environment")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_forever, daemon=True, name="okx-dex-ws")
        self._thread.start()
        logger.info("OkxDexWs started")

    def stop(self):
        """Stop WebSocket and wait for thread."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("OkxDexWs stopped")

    def get_events(self) -> list:
        """Drain and return all buffered events since last call.
        Returns list of normalized trade dicts.
        """
        events = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    # ── Internal ──

    def _run_forever(self):
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=PING_INTERVAL, ping_timeout=10)
            except Exception as e:
                logger.error(f"WS run_forever error: {e}")

            if self._running:
                logger.info(f"Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)

    def _on_open(self, ws):
        self._connected = True
        self._logged_in = False
        self._subscribed.clear()
        logger.info("WS connected, authenticating...")

        ts, sign = _make_sign(self.secret)
        login = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": ts,
                "sign": sign,
            }]
        }
        ws.send(json.dumps(login))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        op = data.get("op", "")
        event = data.get("event", "")

        # Login response
        if event == "login":
            if data.get("code") == "0":
                self._logged_in = True
                logger.info("WS login OK, subscribing...")
                self._subscribe_all(ws)
            else:
                logger.error(f"WS login failed: {data.get('msg', '')} (code={data.get('code')})")
                self._error_count += 1
            return

        # Subscribe confirm
        if event == "subscribe":
            ch = data.get("arg", {}).get("channel", "?")
            self._subscribed.add(ch)
            logger.info(f"WS subscribed: {ch}")
            return

        # Error
        if event == "error":
            logger.error(f"WS error: {data.get('msg', '')} (code={data.get('code')})")
            self._error_count += 1
            return

        # Data push
        if event == "" and "data" in data:
            channel_data = data.get("data", [])
            for item in channel_data:
                normalized = _normalize_event(item)
                try:
                    self._queue.put_nowait(normalized)
                    self._event_count += 1
                    self._last_event_ts = time.time()
                except queue.Full:
                    logger.warning("Event queue full, dropping oldest")
                    try:
                        self._queue.get_nowait()  # drop oldest
                        self._queue.put_nowait(normalized)
                    except Exception:
                        pass

    def _on_error(self, ws, error):
        logger.error(f"WS error: {error}")
        self._error_count += 1
        self._connected = False

    def _on_close(self, ws, close_code, close_msg):
        self._connected = False
        self._logged_in = False
        self._subscribed.clear()
        logger.info(f"WS closed (code={close_code}, msg={close_msg})")

    def _subscribe_all(self, ws):
        """Subscribe to all configured channels."""
        for ch in self.channels:
            sub_args = {"channel": ch}
            ws.send(json.dumps({"op": "subscribe", "args": [sub_args]}))
            time.sleep(0.05)  # small gap to avoid flooding
