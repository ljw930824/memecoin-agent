import os
import sys
import time
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ACTIVE = os.path.join(ROOT, "scripts", "active")
SCRIPTS = os.path.join(ROOT, "scripts")
Dashboard = os.path.join(ROOT, "scripts", "dashboard")
sys.path.insert(0, ACTIVE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, Dashboard)

import okx_dex_ws  # noqa: E402
import okx_dex_rest  # noqa: E402
import ws_price_feed  # noqa: E402
import qclaw_trading_common as common  # noqa: E402
import realtime_sm_monitor as monitor  # noqa: E402
import dashboard_server  # noqa: E402


class ActivePipelineTests(unittest.TestCase):
    def test_okx_v6_rest_normalizes_signal_list(self):
        rest = okx_dex_rest.OkxDexRest(chain_indexes=["501"])
        with mock.patch.object(rest, "_post", return_value={
            "code": "0",
            "data": [{
                "chainIndex": "501",
                "timestamp": int(time.time() * 1000) - 1000,
                "token": {
                    "tokenAddress": "TokenCA",
                    "symbol": "T",
                    "marketCapUsd": "45000",
                },
                "price": "1.25",
                "walletType": "SMART_MONEY",
                "triggerWalletCount": "2",
                "triggerWalletAddress": "wallet-a,wallet-b",
                "amountUsd": "1200",
                "soldRatioPercent": "0",
            }],
        }):
            events = rest.fetch_signal_events()
        self.assertTrue(rest.last_signal_ok)
        self.assertEqual(rest.last_signal_raw_count, 1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["source"], "okx_v6_rest_signal")
        self.assertEqual(events[0]["tradeType"], "1")
        self.assertEqual(events[0]["tokenContractAddress"], "TokenCA")
        self.assertNotEqual(events[0]["txHash"], events[1]["txHash"])

    def test_okx_v6_rest_normalizes_batch_prices(self):
        rest = okx_dex_rest.OkxDexRest(chain_indexes=["501"])
        with mock.patch.object(rest, "_post", return_value={
            "code": "0",
            "data": [{
                "chainIndex": "501",
                "tokenContractAddress": "TokenCA",
                "price": "1.5",
            }],
        }):
            prices = rest.fetch_prices([{
                "chainIndex": "501",
                "tokenContractAddress": "TokenCA",
            }])
        self.assertTrue(rest.last_price_ok)
        self.assertEqual(prices["501:TokenCA"], 1.5)

    def test_monitor_prefers_okx_v6_rest_signal_source(self):
        class RestSource:
            last_signal_ok = True
            last_signal_error = ""

            def fetch_signal_events(self):
                return [{
                    "event_type": "trade",
                    "txHash": "rest-signal-1",
                    "tradeType": "1",
                }]

        original_rest = monitor._REST_CLIENT
        original_ws = monitor._WS_CLIENT
        original_oc_run = monitor.oc_run
        try:
            monitor._REST_CLIENT = RestSource()
            monitor._WS_CLIENT = None

            def fail_if_called(*args, **kwargs):
                raise AssertionError("OnchainOS fallback should not run after REST success")

            monitor.oc_run = fail_if_called
            trades = monitor.fetch_tracker({})
            self.assertEqual(trades[0]["txHash"], "rest-signal-1")
        finally:
            monitor._REST_CLIENT = original_rest
            monitor._WS_CLIENT = original_ws
            monitor.oc_run = original_oc_run

    def test_legacy_ws_facade_has_only_dex_v6_transport(self):
        with open(os.path.join(SCRIPTS, "ws_price_feed.py"), encoding="utf-8") as handle:
            source = handle.read().lower()
        legacy_host = "wss://" + "ws." + "okx.com"
        self.assertNotIn(legacy_host, source)
        self.assertIn("wsdex.okx.com/ws/v6/dex", source)
        self.assertFalse(ws_price_feed.cex_ws.start())
        self.assertFalse(ws_price_feed.status()["cex"]["enabled"])

    def test_legacy_ws_facade_uses_chain_and_contract_price_key(self):
        ws_price_feed.price_store.update("501:TokenCA", 1.5, ts=1700000000000)
        self.assertEqual(ws_price_feed.get_price("501", "TokenCA"), 1.5)

    def test_ws_normalizes_timestamp_and_common_aliases(self):
        event = okx_dex_ws._normalize_event({
            "chainId": 501,
            "address": "wallet",
            "tokenAddress": "token",
            "symbol": "T",
            "marketCapUsd": "32000",
            "price": "1.25",
            "action": "buy",
            "timestamp": 1_700_000_000,
            "hash": "tx",
        })
        self.assertEqual(event["chainIndex"], "501")
        self.assertEqual(event["tradeType"], "1")
        self.assertEqual(event["tradeTime"], "1700000000000")
        self.assertEqual(event["txHash"], "tx")
        self.assertEqual(event["marketCap"], "32000")

    def test_ws_normalizes_okx_kol_smartmoney_payload_shape(self):
        event = okx_dex_ws._normalize_event({
            "baseTokenChainIndex": "501",
            "baseTokenContractAddress": "TokenCA",
            "baseTokenSymbol": "T",
            "marketCap": "45000",
            "tradePrice": "1.25",
            "tradeType": "1",
            "tradeTime": 1_700_000_000_000,
            "walletAddress": "wallet",
        })
        self.assertEqual(event["chainIndex"], "501")
        self.assertEqual(event["tokenContractAddress"], "TokenCA")
        self.assertEqual(event["tokenSymbol"], "T")
        self.assertEqual(event["tokenPrice"], "1.25")

    def test_ws_normalizes_direct_signal_into_deduplicated_buy_event(self):
        events = okx_dex_ws._normalize_signal_events({
            "chainIndex": "501",
            "timestamp": 1_700_000_000_000,
            "token": {
                "tokenAddress": "TokenCA",
                "symbol": "T",
                "marketCapUsd": "45000",
            },
            "price": "1.25",
            "walletType": "1",
            "triggerWalletCount": "2",
            "triggerWalletAddress": "wallet-a,wallet-b",
        }, {"channel": okx_dex_ws.SIGNAL_CHANNEL})
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["tradeType"] == "1" for e in events))
        self.assertTrue(all(e["signal_type"] == "smart_money_signal" for e in events))
        self.assertNotEqual(events[0]["txHash"], events[1]["txHash"])

    def test_ws_parses_v6_signal_fields_from_arg(self):
        ws = okx_dex_ws.OkxDexWs(channels=[okx_dex_ws.SIGNAL_CHANNEL], chain_indexes=["501"])
        ws._connected = True
        ws._logged_in = True
        ws._on_message(None, {
            "arg": {
                "channel": okx_dex_ws.SIGNAL_CHANNEL,
                "chainIndex": "501",
                "timestamp": "1700000000000",
                "token": {
                    "tokenAddress": "TokenCA",
                    "symbol": "T",
                    "marketCapUsd": "45000",
                },
                "price": "1.25",
                "walletType": "1,2",
                "triggerWalletCount": "2",
                "triggerWalletAddress": "wallet-a,wallet-b",
                "amountUsd": "128000.00",
                "soldRatioPercentage": "0",
            },
        })
        events = ws.get_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["signal_type"], "smart_money_signal")
        self.assertEqual(events[0]["chainIndex"], "501")
        self.assertEqual(events[0]["tokenContractAddress"], "TokenCA")

    def test_ws_is_not_ready_until_v6_entry_subscription_succeeds(self):
        ws = okx_dex_ws.OkxDexWs(channels=[okx_dex_ws.SIGNAL_CHANNEL], chain_indexes=["501"])
        ws._connected = True
        ws._logged_in = True
        self.assertTrue(ws.is_authenticated)
        self.assertFalse(ws.is_ready)
        ws._on_message(None, {
            "event": "error",
            "code": "60029",
            "msg": "Only users who are in the whitelist are allowed to subscribe to this channel.",
        })
        self.assertFalse(ws.is_ready)
        self.assertEqual(ws.feed_status, "authenticated_no_entry_subscription")
        ws._on_message(None, {
            "event": "subscribe",
            "arg": {
                "channel": okx_dex_ws.SIGNAL_CHANNEL,
                "chainIndex": "501",
            },
        })
        self.assertTrue(ws.is_ready)
        self.assertEqual(ws.subscribed_channels, [okx_dex_ws.SIGNAL_CHANNEL])

    def test_trade_time_accepts_seconds_and_milliseconds(self):
        self.assertEqual(monitor.trade_time_ms(1_700_000_000), 1_700_000_000_000)
        self.assertEqual(monitor.trade_time_ms(1_700_000_000_000), 1_700_000_000_000)

    def test_ws_normalizes_price_channel_event(self):
        event = okx_dex_ws._normalize_price_event(
            {"price": "1.50", "time": 1_700_000_001_000, "marketCap": "45000"},
            {
                "channel": "price",
                "chainIndex": "501",
                "tokenContractAddress": "TokenCA",
            },
        )
        self.assertEqual(event["event_type"], "price")
        self.assertEqual(event["tokenContractAddress"], "TokenCA")
        self.assertEqual(event["tokenPrice"], "1.50")
        self.assertEqual(event["tradeTime"], "1700000001000")

    def test_price_subscription_messages_are_scoped_to_positions(self):
        class FakeWs:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

        ws = okx_dex_ws.OkxDexWs()
        fake = FakeWs()
        ws._ws = fake
        ws._connected = True
        ws._logged_in = True
        self.assertTrue(ws.sync_price_subscriptions([
            {"chainIndex": "501", "tokenContractAddress": "TokenCA"},
        ]))
        self.assertEqual(len(fake.messages), 1)
        self.assertIn('"channel": "price"', fake.messages[0])
        self.assertIn('"tokenContractAddress": "TokenCA"', fake.messages[0])
        ws.sync_price_subscriptions([])
        self.assertEqual(len(fake.messages), 2)
        self.assertIn('"op": "unsubscribe"', fake.messages[1])

    def test_fast_exit_is_full_exit_by_default(self):
        self.assertTrue(monitor.FAST_EXIT_MODE)
        self.assertEqual(monitor.TIME_TIERS[0][2], monitor.QUICK_TP_PCT)
        self.assertEqual(monitor.TIME_TIERS[0][3], monitor.QUICK_TP_SELL_PCT)
        self.assertEqual(monitor.QUICK_TP_SELL_PCT, 1.0)

    def test_workspace_defaults_to_repository_root(self):
        self.assertEqual(common.workspace_root(os.path.join(ACTIVE, "x.py")), ROOT)

    def test_ws_start_fails_closed_without_complete_runtime(self):
        with mock.patch.dict(os.environ, {
            "OKX_API_KEY": "",
            "OKX_SECRET_KEY": "",
            "OKX_PASSPHRASE": "",
        }, clear=False):
            ws = okx_dex_ws.OkxDexWs()
            self.assertFalse(ws.start())

    def test_healthy_idle_ws_does_not_call_rest_fallback(self):
        class IdleWs:
            is_ready = True

            def get_events(self):
                return []

        original_ws = monitor._WS_CLIENT
        original_oc_run = monitor.oc_run
        try:
            monitor._WS_CLIENT = IdleWs()

            def fail_if_called(*args, **kwargs):
                raise AssertionError("REST fallback should not run while WS is healthy")

            monitor.oc_run = fail_if_called
            self.assertEqual(monitor.fetch_tracker({}), [])
        finally:
            monitor._WS_CLIENT = original_ws
            monitor.oc_run = original_oc_run

    def test_authenticated_ws_without_entry_subscription_uses_rest_fallback(self):
        class AuthenticatedWithoutFeedWs:
            is_authenticated = True
            is_ready = False

            def get_events(self):
                return []

        original_ws = monitor._WS_CLIENT
        original_oc_run = monitor.oc_run
        try:
            monitor._WS_CLIENT = AuthenticatedWithoutFeedWs()
            calls = []

            def fake_oc_run(args, timeout=None):
                calls.append(args)
                return '{"ok": true, "data": {"trades": []}}', 0

            monitor.oc_run = fake_oc_run
            self.assertEqual(monitor.fetch_tracker({}), [])
            self.assertEqual(len(calls), 2)
        finally:
            monitor._WS_CLIENT = original_ws
            monitor.oc_run = original_oc_run

    def test_price_events_drive_exit_cache_but_are_not_entry_trades(self):
        class PriceWs:
            is_ready = True

            def get_events(self):
                return [{
                    "event_type": "price",
                    "tokenContractAddress": "TokenCA",
                    "tokenPrice": "2.5",
                }]

        original_ws = monitor._WS_CLIENT
        original_cache = dict(monitor._price_cache)
        try:
            monitor._WS_CLIENT = PriceWs()
            monitor._price_cache.clear()
            self.assertEqual(monitor.fetch_tracker({"positions": {}}), [])
            self.assertEqual(monitor._price_cache["tokenca"], (2.5, mock.ANY))
        finally:
            monitor._WS_CLIENT = original_ws
            monitor._price_cache.clear()
            monitor._price_cache.update(original_cache)

    def test_dashboard_pid_probe_is_read_only_on_windows(self):
        if os.name != "nt":
            self.skipTest("Windows-specific PID probe")
        with mock.patch.object(dashboard_server.os, "kill", side_effect=AssertionError("PID probe must not kill")):
            self.assertTrue(dashboard_server.process_alive(os.getpid()))


if __name__ == "__main__":
    unittest.main()
