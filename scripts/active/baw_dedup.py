# -*- coding: utf-8 -*-
"""
baaw_dedup.py — BAW 去重层
共享文件: data/baw-bought-tokens.json
格式: { "contract_address_lower": { "ticker": "...", "bought_ts": 123, "tx": "..." }, ... }

用法:
  from baw_dedup import is_token_bought, mark_token_bought, bought_tokens_list
"""
import json, os, sys, time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from qclaw_trading_common import workspace_root, locked_read_json, locked_write_json

DEDUP_FILE = os.path.join(workspace_root(__file__), "data", "baw-bought-tokens.json")
_lock = None  # lightweight — rely on atomic writes


def _load():
    if os.path.exists(DEDUP_FILE):
        try:
            return locked_read_json(DEDUP_FILE, {})
        except Exception:
            pass
    return {}


def _save(data):
    locked_write_json(DEDUP_FILE, data, indent=2)


def is_token_bought(ca):
    """Check if BAW has already bought this token (any chain)."""
    return ca.lower() in _load()


def mark_token_bought(ca, ticker, tx="", chain="56"):
    """Record that BAW bought this token."""
    data = _load()
    data[ca.lower()] = {
        "ticker": ticker,
        "bought_ts": int(time.time()),
        "tx": tx,
        "chain": chain,
    }
    _save(data)


def clear_token(ca):
    """Remove token from dedup (after full sell)."""
    data = _load()
    data.pop(ca.lower(), None)
    _save(data)


def bought_tokens_list():
    """Return list of (ca_lower, info_dict) for all bought tokens."""
    return list(_load().items())


def clear_all():
    """Emergency: clear all dedup entries."""
    _save({})
