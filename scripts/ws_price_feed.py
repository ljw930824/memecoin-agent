"""
OKX DEX WebSocket compatibility facade.

The live project path uses the canonical DEX WebSocket V6 client in
``scripts/active/okx_dex_ws.py``.  This module remains as a compatibility
entry point for older launchers, but it no longer creates a separate CEX
symbol feed.  DEX V6 price subscriptions require a chain index and token
contract address; a CEX-style symbol such as ``SOL-USDT`` is therefore not a
valid price key here.
"""

import logging
import os
import sys
import threading
import time


log = logging.getLogger("okx_ws")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ACTIVE_DIR = os.path.join(_SCRIPT_DIR, "active")
if _ACTIVE_DIR not in sys.path:
    sys.path.insert(0, _ACTIVE_DIR)

from okx_dex_ws import (  # noqa: E402
    SIGNAL_CHANNEL,
    SMART_MONEY_ACTIVITY_CHANNEL,
    OkxDexWs,
)


OKX_DEX_WS_URL = os.environ.get(
    "OKX_DEX_WS_URL", "wss://wsdex.okx.com/ws/v6/dex"
)


class SignalStore:
    """Thread-safe compatibility store for normalized DEX V6 entry events."""

    def __init__(self):
        self._lock = threading.Lock()
        self._signals = []
        self._callbacks = []
        self._last_signal_ts = 0.0

    def add(self, signal: dict):
        with self._lock:
            self._signals.append(signal)
            self._last_signal_ts = time.time()
            if len(self._signals) > 1000:
                self._signals = self._signals[-1000:]
        for callback in list(self._callbacks):
            try:
                callback(signal)
            except Exception as exc:
                log.warning("signal callback error: %s", exc)

    def get_recent(self, n=10):
        with self._lock:
            return self._signals[-n:]

    def get_all(self):
        with self._lock:
            return list(self._signals)

    def on_signal(self, callback):
        self._callbacks.append(callback)

    def last_signal_age(self):
        with self._lock:
            if not self._last_signal_ts:
                return float("inf")
            return time.time() - self._last_signal_ts


class PriceStore:
    """Thread-safe DEX V6 price store keyed by ``chainIndex:contract``."""

    def __init__(self):
        self._lock = threading.Lock()
        self._prices = {}
        self._callbacks = []

    def update(self, key: str, px: float, side: str = "", ts: int = 0):
        with self._lock:
            self._prices[key] = {
                "px": px,
                "side": side,
                "ts": ts,
                "updated": time.time(),
            }
        for callback in list(self._callbacks):
            try:
                callback(key, px, side, ts)
            except Exception as exc:
                log.warning("price callback error: %s", exc)

    def get(self, key: str):
        with self._lock:
            return self._prices.get(key)

    def get_all(self):
        with self._lock:
            return dict(self._prices)

    def on_update(self, callback):
        self._callbacks.append(callback)

    def age(self, key: str):
        with self._lock:
            entry = self._prices.get(key)
            if entry:
                return time.time() - entry["updated"]
        return float("inf")


signal_store = SignalStore()
price_store = PriceStore()


class OKXCEXWebSocket:
    """Disabled compatibility shell for the removed CEX symbol feed."""

    def __init__(self, channels=None):
        self.channels = channels or []
        self._running = False

    def start(self):
        log.warning(
            "CEX symbol feed is disabled; use DEX V6 price subscriptions "
            "with chainIndex and tokenContractAddress"
        )
        return False

    def stop(self):
        self._running = False


class OKXDEXWebSocket:
    """Compatibility adapter backed by the canonical DEX V6 client."""

    def __init__(self, api_key=None, secret=None, passphrase=None):
        # Keep the old constructor surface, but let the canonical client read
        # the same runtime credentials as the active monitor.
        if api_key is not None:
            os.environ["OKX_API_KEY"] = api_key
        if secret is not None:
            os.environ["OKX_SECRET_KEY"] = secret
        if passphrase is not None:
            os.environ["OKX_PASSPHRASE"] = passphrase

        self._client = OkxDexWs(
            channels=[SMART_MONEY_ACTIVITY_CHANNEL, SIGNAL_CHANNEL],
            chain_indexes=["501", "56"],
        )
        self._pump_running = False
        self._pump_thread = None

    @property
    def _running(self):
        return self._client._running

    @property
    def ws(self):
        return self._client._ws

    def _pump_events(self):
        while self._pump_running:
            for event in self._client.get_events():
                if event.get("event_type") == "price":
                    price = event.get("tokenPrice")
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        continue
                    chain = event.get("chainIndex", "")
                    contract = event.get("tokenContractAddress", "")
                    if chain and contract:
                        price_store.update(
                            f"{chain}:{contract}",
                            price,
                            "",
                            int(event.get("tradeTime") or 0),
                        )
                else:
                    signal_store.add(event)
            time.sleep(0.1)

    def start(self):
        started = self._client.start()
        if started and not self._pump_running:
            self._pump_running = True
            self._pump_thread = threading.Thread(
                target=self._pump_events,
                daemon=True,
                name="okx-dex-v6-compat-pump",
            )
            self._pump_thread.start()
        return started

    def stop(self):
        self._pump_running = False
        self._client.stop()
        if self._pump_thread and self._pump_thread.is_alive():
            self._pump_thread.join(timeout=2)

    def is_logged_in(self):
        return self._client.is_authenticated

    def sync_price_subscriptions(self, items):
        return self._client.sync_price_subscriptions(items)

    @property
    def feed_status(self):
        return self._client.feed_status

    @property
    def subscribed_channels(self):
        return self._client.subscribed_channels


cex_ws = OKXCEXWebSocket()
dex_ws = OKXDEXWebSocket()


def _price_key(chain_index_or_key: str, token_contract_address: str = ""):
    if token_contract_address:
        return f"{chain_index_or_key}:{token_contract_address}"
    return chain_index_or_key


def get_price(chain_index_or_key: str, token_contract_address: str = ""):
    """Return a DEX V6 price using ``chainIndex`` and contract address."""
    entry = price_store.get(_price_key(chain_index_or_key, token_contract_address))
    return entry["px"] if entry else None


def get_price_fresh(
    chain_index_or_key: str,
    token_contract_address: str = "",
    max_age_sec=30,
):
    """Return a DEX V6 price only when it is fresh."""
    # Accept the former ``get_price_fresh(key, max_age_sec)`` positional
    # shape while keeping the V6 chain/address form as the canonical API.
    if isinstance(token_contract_address, (int, float)) and max_age_sec == 30:
        max_age_sec = token_contract_address
        token_contract_address = ""
    key = _price_key(chain_index_or_key, token_contract_address)
    if price_store.age(key) < max_age_sec:
        entry = price_store.get(key)
        return entry["px"] if entry else None
    return None


def get_recent_signals(n=10):
    return signal_store.get_recent(n)


def start_all():
    """Start the canonical DEX V6 signal and price client only."""
    started = dex_ws.start()
    log.info("DEX V6 WebSocket feed started=%s", started)
    return started


def stop_all():
    dex_ws.stop()


def status():
    """Return compatibility status without exposing a legacy CEX feed."""
    return {
        "cex": {
            "running": False,
            "enabled": False,
            "prices": [],
        },
        "dex": {
            "running": dex_ws._running,
            "logged_in": dex_ws.is_logged_in(),
            "feed_status": dex_ws.feed_status,
            "subscribed_channels": dex_ws.subscribed_channels,
            "signals_count": len(signal_store.get_all()),
            "last_signal_age": signal_store.last_signal_age(),
        },
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    start_all()
    try:
        while True:
            time.sleep(10)
            current = status()
            dex = current["dex"]
            print(
                f"DEX V6: {dex['running']} | logged in: {dex['logged_in']} "
                f"| feed: {dex['feed_status']} | signals: {dex['signals_count']}"
            )
    except KeyboardInterrupt:
        stop_all()
