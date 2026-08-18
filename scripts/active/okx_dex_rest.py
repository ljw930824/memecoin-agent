"""Direct OKX OnchainOS DEX REST V6 client for the dry-run monitor.

This client intentionally covers only read-only market data:

* ``POST /api/v6/dex/market/signal/list`` for Smart Money signals
* ``POST /api/v6/dex/market/price`` for held-token prices

It does not place orders and never logs credential material.  The monitor
keeps the existing OnchainOS CLI path as a secondary fallback when the V6
REST entitlement or network is unavailable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


REST_BASE_URL = os.environ.get("OKX_DEX_REST_BASE_URL", "https://web3.okx.com")
SIGNAL_PATH = "/api/v6/dex/market/signal/list"
PRICE_PATH = "/api/v6/dex/market/price"
REST_TIMEOUT_SEC = float(os.environ.get("OKX_REST_TIMEOUT_SEC", "10"))


class OkxDexRestError(RuntimeError):
    """A safe-to-display REST error without credentials or request bodies."""


def _credential(name: str) -> str:
    """Read explicit REST credentials, then the direct WS, then PROD names."""
    return (
        os.environ.get(f"OKX_REST_{name}", "").strip()
        or os.environ.get(f"OKX_{name}", "").strip()
        or os.environ.get(f"OKX_PROD_{name}", "").strip()
    )


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _epoch_ms(value: Any) -> str:
    try:
        timestamp = int(float(value or 0))
    except (TypeError, ValueError):
        return ""
    if 0 < timestamp < 10_000_000_000:
        timestamp *= 1000
    return str(timestamp) if timestamp > 0 else ""


def _chain_index(chain: Any) -> str:
    text = str(chain or "").strip().lower()
    return {"solana": "501", "bsc": "56", "bnb": "56"}.get(text, str(chain or ""))


def _wallets(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def normalize_signal_item(item: Dict[str, Any], requested_chain: str) -> List[Dict[str, Any]]:
    """Convert one V6 REST signal into the monitor's activity-shaped events."""
    item = item or {}
    token = item.get("token") or {}
    chain = _chain_index(item.get("chainIndex") or requested_chain)
    token_ca = str(
        token.get("tokenAddress")
        or token.get("tokenContractAddress")
        or item.get("tokenContractAddress")
        or ""
    ).strip()
    if not chain or not token_ca:
        return []

    timestamp = _epoch_ms(item.get("timestamp") or item.get("time"))
    wallets = _wallets(item.get("triggerWalletAddress")) or ["signal"]
    common = {
        "event_type": "trade",
        "signal_type": "smart_money_signal",
        "source": "okx_v6_rest_signal",
        "chainIndex": chain,
        "tokenContractAddress": token_ca,
        "tokenSymbol": token.get("symbol") or token.get("tokenSymbol", ""),
        "marketCap": token.get("marketCapUsd") or item.get("marketCapUsd", ""),
        "quoteTokenAmount": item.get("amountUsd", ""),
        "quoteTokenSymbol": "USD",
        "tokenPrice": item.get("price", ""),
        "realizedPnlUsd": "0",
        "tradeType": "1",
        "tradeTime": timestamp,
        "trackerType": [1],
        "signalWalletCount": item.get("triggerWalletCount", ""),
        "soldRatioPercentage": item.get("soldRatioPercent")
        or item.get("soldRatioPercentage", ""),
    }

    events = []
    for wallet in wallets:
        dedup_material = json.dumps(
            ["okx-v6-rest-signal", chain, token_ca, timestamp, wallet],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        event = dict(common)
        event["walletAddress"] = wallet
        event["txHash"] = "rest-signal-" + hashlib.sha256(
            dedup_material.encode("utf-8")
        ).hexdigest()[:48]
        event["blockTimestamp"] = str(int(timestamp) // 1000) if timestamp else ""
        events.append(event)
    return events


class OkxDexRest:
    """Small synchronous, read-only OKX DEX V6 REST client."""

    def __init__(self, chain_indexes: Optional[Iterable[str]] = None):
        self.chain_indexes = [str(value) for value in (chain_indexes or ("501", "56"))]
        self.api_key = _credential("API_KEY")
        self.secret = _credential("SECRET_KEY")
        self.passphrase = _credential("PASSPHRASE")
        self.project_id = _credential("PROJECT_ID")
        self.last_signal_ok: Optional[bool] = None
        self.last_signal_error = ""
        self.last_signal_count = 0
        self.last_signal_raw_count = 0
        self.last_price_ok: Optional[bool] = None
        self.last_price_error = ""
        self.last_price_count = 0
        self.request_count = 0
        self.last_request_ts = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.secret and self.passphrase)

    @property
    def mode(self) -> str:
        return "okx_v6_rest" if self.enabled else "onchainos_fallback_missing_credentials"

    def _post(self, path: str, payload: Any) -> Dict[str, Any]:
        if not self.enabled:
            raise OkxDexRestError("OKX REST credentials are incomplete")

        timestamp = _timestamp_iso()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        prehash = timestamp + "POST" + path + body
        signature = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "memecoin-agent/1.0",
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
        }
        if self.project_id:
            headers["OK-ACCESS-PROJECT"] = self.project_id
        request = urllib.request.Request(
            REST_BASE_URL.rstrip("/") + path,
            data=body.encode("utf-8"),
            method="POST",
            headers=headers,
        )
        self.request_count += 1
        self.last_request_ts = time.time()
        try:
            with urllib.request.urlopen(request, timeout=REST_TIMEOUT_SEC) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise OkxDexRestError(f"HTTP {exc.code}: {_safe_error_message(raw)}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OkxDexRestError(f"network error: {exc}") from exc

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OkxDexRestError("invalid JSON response") from exc
        if not isinstance(result, dict):
            raise OkxDexRestError("unexpected REST response shape")
        if str(result.get("code", "0")) != "0":
            raise OkxDexRestError(
                f"OKX code {result.get('code')}: {result.get('msg') or 'request failed'}"
            )
        return result

    def fetch_signal_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        raw_count = 0
        max_age_ms = int(float(os.environ.get("OKX_REST_SIGNAL_MAX_AGE_SEC", "60")) * 1000)
        now_ms = int(time.time() * 1000)
        try:
            for chain in self.chain_indexes:
                payload = [{
                    "chainIndex": chain,
                    "walletType": "1",
                    "minAmountUsd": os.environ.get("OKX_REST_MIN_AMOUNT_USD", "500"),
                    "minAddressCount": os.environ.get("OKX_REST_MIN_ADDRESS_COUNT", "1"),
                    "minMarketCapUsd": os.environ.get("OKX_REST_MIN_MCAP_USD", "30000"),
                    "limit": os.environ.get("OKX_REST_SIGNAL_LIMIT", "100"),
                }]
                response = self._post(SIGNAL_PATH, payload)
                items = response.get("data") or []
                if isinstance(items, dict):
                    items = items.get("items") or items.get("signals") or []
                if not isinstance(items, list):
                    items = []
                raw_count += len(items)
                for item in items:
                    if isinstance(item, dict):
                        events.extend(normalize_signal_item(item, chain))
            fresh_events = []
            for event in events:
                try:
                    event_ts = int(event.get("tradeTime") or 0)
                except (TypeError, ValueError):
                    event_ts = 0
                age_ms = now_ms - event_ts if event_ts else max_age_ms + 1
                if 0 <= age_ms <= max_age_ms:
                    fresh_events.append(event)
            self.last_signal_ok = True
            self.last_signal_error = ""
            self.last_signal_raw_count = raw_count
            self.last_signal_count = len(fresh_events)
            return fresh_events
        except OkxDexRestError as exc:
            self.last_signal_ok = False
            self.last_signal_error = str(exc)
            self.last_signal_raw_count = raw_count
            self.last_signal_count = 0
            return []

    def fetch_prices(self, items: Iterable[Dict[str, Any]]) -> Dict[str, float]:
        request_items = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            chain = _chain_index(item.get("chainIndex") or item.get("chain"))
            contract = str(
                item.get("tokenContractAddress") or item.get("token_ca") or ""
            ).strip()
            if chain and contract:
                if chain == "56":
                    contract = contract.lower()
                request_items.append({
                    "chainIndex": chain,
                    "tokenContractAddress": contract,
                })
        if not request_items:
            self.last_price_ok = True
            self.last_price_error = ""
            self.last_price_count = 0
            return {}

        try:
            response = self._post(PRICE_PATH, request_items)
            result = {}
            for item in response.get("data") or []:
                if not isinstance(item, dict):
                    continue
                chain = _chain_index(item.get("chainIndex"))
                contract = str(item.get("tokenContractAddress") or "").strip()
                try:
                    price = float(item.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                if chain and contract and price > 0:
                    result[f"{chain}:{contract.lower() if chain == '56' else contract}"] = price
            self.last_price_ok = True
            self.last_price_error = ""
            self.last_price_count = len(result)
            return result
        except OkxDexRestError as exc:
            self.last_price_ok = False
            self.last_price_error = str(exc)
            self.last_price_count = 0
            return {}

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "project_configured": bool(self.project_id),
            "last_signal_ok": self.last_signal_ok,
            "last_signal_error": self.last_signal_error,
            "last_signal_count": self.last_signal_count,
            "last_signal_raw_count": self.last_signal_raw_count,
            "last_price_ok": self.last_price_ok,
            "last_price_error": self.last_price_error,
            "last_price_count": self.last_price_count,
            "request_count": self.request_count,
            "last_request_ts": self.last_request_ts,
            "chain_indexes": list(self.chain_indexes),
        }


def _safe_error_message(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:200]
    if isinstance(data, dict):
        return f"{data.get('code', '')} {data.get('msg', '')}".strip()[:200]
    return "unexpected error response"
