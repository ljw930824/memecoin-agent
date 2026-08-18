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
    websocket = None

logger = logging.getLogger("okx_dex_ws")

WS_URL = "wss://wsdex.okx.com/ws/v6/dex"
PING_INTERVAL = 25  # seconds
RECONNECT_DELAY = 5  # seconds
MAX_QUEUE_SIZE = 5000
SMART_MONEY_ACTIVITY_CHANNEL = "kol_smartmoney-tracker-activity"
SIGNAL_CHANNEL = "dex-market-new-signal-openapi"

# tradeType: "1"=buy, "2"=sell (same format as REST tracker, no conversion needed)


def _epoch_ms(value) -> str:
    """Normalize seconds/milliseconds timestamps from WS payload variants."""
    try:
        ts = int(float(value or 0))
    except (TypeError, ValueError):
        return ""
    if 0 < ts < 10_000_000_000:
        ts *= 1000
    return str(ts) if ts > 0 else ""


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
    raw_trade_type = data_item.get("tradeType") or data_item.get("action") or ""
    trade_type = str(raw_trade_type).strip().lower()
    if trade_type in ("buy", "1"):
        trade_type = "1"
    elif trade_type in ("sell", "2"):
        trade_type = "2"
    raw_chain = (
        data_item.get("chainIndex")
        or data_item.get("chainId")
        or data_item.get("chain")
        or data_item.get("baseTokenChainIndex")
        or ""
    )
    chain_text = str(raw_chain).strip().lower()
    chain_index = {"solana": "501", "bsc": "56", "bnb": "56"}.get(chain_text, str(raw_chain))
    trade_time = _epoch_ms(
        data_item.get("tradeTime")
        or data_item.get("timestamp")
        or data_item.get("time")
    )
    return {
        "event_type": "trade",
        "chainIndex": chain_index,
        "walletAddress": data_item.get("walletAddress") or data_item.get("address", ""),
        "tokenContractAddress": (
            data_item.get("tokenContractAddress")
            or data_item.get("tokenAddress")
            or data_item.get("baseTokenContractAddress", "")
        ),
        "tokenSymbol": (
            data_item.get("tokenSymbol")
            or data_item.get("symbol")
            or data_item.get("baseTokenSymbol", "")
        ),
        "marketCap": data_item.get("marketCap") or data_item.get("marketCapUsd") or data_item.get("mcap", ""),
        "quoteTokenAmount": data_item.get("quoteTokenAmount", ""),
        "quoteTokenSymbol": data_item.get("quoteTokenSymbol", ""),
        "tokenPrice": (
            data_item.get("tokenPrice")
            or data_item.get("price")
            or data_item.get("tradePrice", "")
        ),
        "realizedPnlUsd": data_item.get("realizedPnlUsd", "0"),
        "tradeType": trade_type,
        "tradeTime": trade_time,
        "txHash": data_item.get("txHash") or data_item.get("transactionHash") or data_item.get("hash", ""),
        "trackerType": data_item.get("trackerType", []),
        # Computed: blockTimestamp from tradeTime (ms→s)
        "blockTimestamp": str(int(trade_time) // 1000) if trade_time else "",
    }


def _normalize_price_event(data_item: dict, channel_arg: dict) -> dict:
    """Normalize OKX ``price``/``price-info`` pushes for exit monitoring."""
    raw_chain = (
        channel_arg.get("chainIndex")
        or data_item.get("chainIndex")
        or data_item.get("chainId")
        or data_item.get("chain")
        or ""
    )
    chain_text = str(raw_chain).strip().lower()
    chain_index = {"solana": "501", "bsc": "56", "bnb": "56"}.get(
        chain_text, str(raw_chain)
    )
    token_ca = (
        channel_arg.get("tokenContractAddress")
        or data_item.get("tokenContractAddress")
        or data_item.get("tokenAddress")
        or ""
    )
    price = data_item.get("price") or data_item.get("tokenPrice") or ""
    price_time = _epoch_ms(data_item.get("time") or data_item.get("timestamp"))
    return {
        "event_type": "price",
        "channel": channel_arg.get("channel", "price"),
        "chainIndex": chain_index,
        "tokenContractAddress": token_ca,
        "tokenPrice": price,
        "marketCap": data_item.get("marketCap") or data_item.get("marketCapUsd") or "",
        "liquidity": data_item.get("liquidity", ""),
        "volume24h": data_item.get("volume24h", ""),
        "tradeTime": price_time,
        "blockTimestamp": str(int(price_time) // 1000) if price_time else "",
    }


def _normalize_signal_events(signal: dict, channel_arg: dict) -> list:
    """Convert an OKX signal push into activity-shaped buy events.

    The signal channel aggregates several trigger wallets and does not expose
    a transaction hash.  Stable synthetic hashes make the existing state
    deduplication safe without pretending these are on-chain tx hashes.
    """
    token = signal.get("token", {}) or {}
    chain = (
        signal.get("chainIndex")
        or channel_arg.get("chainIndex")
        or token.get("chainIndex")
        or ""
    )
    chain_text = str(chain).strip().lower()
    chain = {"solana": "501", "bsc": "56", "bnb": "56"}.get(chain_text, str(chain))
    token_ca = token.get("tokenAddress") or signal.get("tokenContractAddress") or ""
    if not chain or not token_ca:
        return []

    timestamp = _epoch_ms(signal.get("timestamp") or signal.get("time"))
    wallet_types = {
        part.strip() for part in str(signal.get("walletType", "")).split(",") if part.strip()
    }
    if "1" not in wallet_types:
        return []

    wallet_text = str(signal.get("triggerWalletAddress", ""))
    wallets = [item.strip() for item in wallet_text.split(",") if item.strip()] or ["signal"]
    common = {
        "event_type": "trade",
        "signal_type": "smart_money_signal",
        "chainIndex": chain,
        "tokenContractAddress": token_ca,
        "tokenSymbol": token.get("symbol", ""),
        "marketCap": token.get("marketCapUsd") or signal.get("marketCapUsd", ""),
        "quoteTokenAmount": signal.get("amountUsd", ""),
        "quoteTokenSymbol": "USD",
        "tokenPrice": signal.get("price", ""),
        "realizedPnlUsd": "0",
        "tradeType": "1",
        "tradeTime": timestamp,
        "trackerType": [1],
        "signalWalletCount": signal.get("triggerWalletCount", ""),
        "soldRatioPercentage": signal.get("soldRatioPercentage") or signal.get("soldRatioPercent", ""),
    }
    events = []
    for wallet in wallets:
        dedup_key = json.dumps(
            [SIGNAL_CHANNEL, chain, token_ca, timestamp, wallet],
            ensure_ascii=False,
        )
        event = dict(common)
        event["walletAddress"] = wallet
        event["txHash"] = "signal-" + hashlib.sha256(dedup_key.encode()).hexdigest()[:48]
        event["blockTimestamp"] = str(int(timestamp) // 1000) if timestamp else ""
        events.append(event)
    return events


class OkxDexWs:
    """OKX DEX WebSocket v6 client with auto-reconnect and event buffering."""

    def __init__(self, channels=None, chain_indexes=None, wallet_addresses=None):
        """
        Args:
            channels: list of WS channel names, default activity + signal channels
            chain_indexes: optional chain indexes filter (e.g. ['501', '56'])
            wallet_addresses: optional wallet addresses for address-tracker-activity
        """
        if channels is None:
            self.channels = [SMART_MONEY_ACTIVITY_CHANNEL]
            signal_enabled = os.environ.get("OKX_ENABLE_SIGNAL_CHANNEL", "1").strip().lower()
            if signal_enabled not in ("0", "false", "no"):
                self.channels.append(SIGNAL_CHANNEL)
        else:
            self.channels = channels
        self.chain_indexes = chain_indexes or ["501", "56"]
        self.wallet_addresses = wallet_addresses or []
        # ``price`` is the low-latency channel.  Set OKX_PRICE_CHANNEL=price-info
        # when market-cap/liquidity updates are also needed for each position.
        self.price_channel = os.environ.get("OKX_PRICE_CHANNEL", "price").strip() or "price"

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
        self._price_subscriptions = set()
        self._subscription_lock = threading.Lock()
        self._event_count = 0
        self._error_count = 0
        self._dropped_count = 0
        self._last_event_ts = 0
        self._last_message_ts = 0
        self._event_signal = threading.Event()

    # ── Public API ──

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_ready(self) -> bool:
        """True only after transport login has succeeded."""
        return self._connected and self._logged_in

    def is_alive(self) -> bool:
        """Check if the WS thread is still running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def start(self):
        """Start WebSocket connection in background thread."""
        if self._running:
            return True
        if websocket is None:
            logger.error("websocket-client is not installed; using REST fallback")
            return False
        if not all((self.api_key, self.secret, self.passphrase)):
            logger.error("OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE are required")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run_forever, daemon=True, name="okx-dex-ws")
        self._thread.start()
        logger.info("OkxDexWs started")
        return True

    def stop(self):
        """Stop WebSocket and wait for thread."""
        self._running = False
        self._event_signal.set()
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
        if self._queue.empty():
            self._event_signal.clear()
        else:
            self._event_signal.set()
        return events

    def wait_for_events(self, timeout: float) -> bool:
        """Wake the consumer as soon as a WS event arrives, with a poll fallback."""
        return self._event_signal.wait(max(0.0, float(timeout)))

    def sync_price_subscriptions(self, items) -> bool:
        """Make per-position price subscriptions match ``items``.

        ``items`` contains ``chainIndex`` and ``tokenContractAddress``.  The
        desired set is retained across reconnects, while subscribe/unsubscribe
        messages are sent immediately when the socket is logged in.
        """
        desired = set()
        for item in items or []:
            if not isinstance(item, dict):
                continue
            chain = item.get("chainIndex") or item.get("chainId") or item.get("chain") or ""
            chain_text = str(chain).strip().lower()
            chain = {"solana": "501", "bsc": "56", "bnb": "56"}.get(chain_text, str(chain))
            token_ca = str(
                item.get("tokenContractAddress") or item.get("tokenAddress") or ""
            ).strip()
            if chain == "56":
                # OKX requires EVM contract addresses in lowercase. Solana
                # addresses are base58 and must retain their original case.
                token_ca = token_ca.lower()
            if chain and token_ca:
                desired.add((self.price_channel, chain, token_ca))

        with self._subscription_lock:
            previous = set(self._price_subscriptions)
            self._price_subscriptions = desired
            ws = self._ws if self._connected and self._logged_in else None

        if ws is None:
            return False

        for channel, chain, token_ca in sorted(previous - desired):
            self._send_subscription(ws, "unsubscribe", channel, chain, token_ca)
        for channel, chain, token_ca in sorted(desired - previous):
            self._send_subscription(ws, "subscribe", channel, chain, token_ca)
        return True

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
                self._event_signal.wait(RECONNECT_DELAY)
                self._event_signal.clear()

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
                self._connected = False
                try:
                    ws.close()
                except Exception:
                    pass
            return

        # Subscribe confirm
        if event == "subscribe":
            arg = data.get("arg", {})
            ch = arg.get("channel", "?")
            self._subscribed.add(ch)
            logger.info(
                "WS subscribed: %s %s %s",
                ch,
                arg.get("chainIndex", ""),
                arg.get("tokenContractAddress", ""),
            )
            return

        # Error
        if event == "error":
            logger.error(f"WS error: {data.get('msg', '')} (code={data.get('code')})")
            self._error_count += 1
            return

        # Data push
        if event == "" and "data" in data:
            channel_data = data.get("data", [])
            channel_arg = data.get("arg", {}) or {}
            channel = channel_arg.get("channel", "")
            normalized_events = []
            for item in channel_data:
                if channel in ("price", "price-info"):
                    normalized_events.append(_normalize_price_event(item, channel_arg))
                else:
                    normalized_events.append(_normalize_event(item))
        else:
            signal_arg = data.get("arg", {}) or {}
            if event == "" and signal_arg.get("channel") == SIGNAL_CHANNEL:
                channel_arg = signal_arg
                signal_payload = data.get("signal") or channel_arg
                normalized_events = _normalize_signal_events(signal_payload, channel_arg)
            else:
                normalized_events = []

        if normalized_events:
            self._last_message_ts = time.time()
            for normalized in normalized_events:
                try:
                    self._queue.put_nowait(normalized)
                    self._event_count += 1
                    self._last_event_ts = time.time()
                    self._event_signal.set()
                except queue.Full:
                    logger.warning("Event queue full, dropping oldest")
                    self._dropped_count += 1
                    try:
                        self._queue.get_nowait()  # drop oldest
                        self._queue.put_nowait(normalized)
                        self._event_signal.set()
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
            if ch == SIGNAL_CHANNEL:
                for chain in self.chain_indexes:
                    self._send_channel_subscription(ws, "subscribe", ch, chain)
            else:
                self._send_channel_subscription(ws, "subscribe", ch)

        with self._subscription_lock:
            price_subscriptions = sorted(self._price_subscriptions)
        for channel, chain, token_ca in price_subscriptions:
            self._send_subscription(ws, "subscribe", channel, chain, token_ca)

    @staticmethod
    def _send_channel_subscription(ws, op: str, channel: str, chain: str = ""):
        args = {"channel": channel}
        if chain:
            args["chainIndex"] = chain
        try:
            ws.send(json.dumps({"op": op, "args": [args]}))
            time.sleep(0.05)
        except Exception as exc:
            logger.warning("WS %s failed for %s/%s: %s", op, channel, chain, exc)

    @staticmethod
    def _send_subscription(ws, op: str, channel: str, chain: str, token_ca: str):
        args = {
            "channel": channel,
            "chainIndex": chain,
            "tokenContractAddress": token_ca,
        }
        try:
            ws.send(json.dumps({"op": op, "args": [args]}))
            time.sleep(0.05)
        except Exception as exc:
            logger.warning("WS %s failed for %s/%s: %s", op, chain, token_ca, exc)
