# -*- coding: utf-8 -*-
"""Regression tests for trading plan P0/P1 helpers (unittest, no pytest required)."""
import os
import sys
import unittest

ACTIVE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ACTIVE_DIR not in sys.path:
    sys.path.insert(0, ACTIVE_DIR)

from qclaw_trading_common import (  # noqa: E402
    canonical_chain_for_onchainos,
    dynamic_sl_tp_from_safety,
    signal_chain_is_solana,
)


class TestChainContract(unittest.TestCase):
    def test_solana_canonical(self):
        self.assertEqual(canonical_chain_for_onchainos("solana", ""), "CT_501")

    def test_signal_chain_is_solana(self):
        self.assertTrue(signal_chain_is_solana({"chain": "CT_501"}))
        self.assertTrue(signal_chain_is_solana({"chain": "solana"}))
        self.assertTrue(signal_chain_is_solana({"chainIndex": "501"}))
        self.assertFalse(signal_chain_is_solana({"chain": "56"}))


class TestDynamicRisk(unittest.TestCase):
    def test_high_impact_widens_sl(self):
        sl, tp, sc = dynamic_sl_tp_from_safety(55, 9.0, -0.08, 0.12)
        self.assertLess(sl, -0.08)
        self.assertLess(sc, 1.0)


if __name__ == "__main__":
    unittest.main()
