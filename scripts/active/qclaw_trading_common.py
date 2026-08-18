# -*- coding: utf-8 -*-
"""
Shared helpers: canonical chain IDs, atomic JSON I/O, cross-process locks,
OKX env (no hardcoded secrets), dynamic risk tiers from safety/impact hints.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple


def workspace_root(anchor_file: Optional[str] = None) -> str:
    """Resolve the workspace without depending on the old OpenClaw install path.

    ``QCLAW_WORKSPACE`` remains an explicit override for an installed deployment.
    When scripts are run from this repository, the root is derived from the
    location of ``scripts/active`` instead of ``~/.qclaw/workspace``.
    """
    override = os.environ.get("QCLAW_WORKSPACE", "").strip()
    if override:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(override)))
    if anchor_file:
        active_dir = os.path.dirname(os.path.abspath(anchor_file))
        return os.path.abspath(os.path.join(active_dir, "..", ".."))
    return os.path.abspath(os.getcwd())

# Canonical chain field used by executors (matches CT_* / numeric Binance id)
CHAIN_SLUG_TO_CANONICAL = {
    "solana": "CT_501",
    "bsc": "56",
    "base": "CT_8453",
    "ethereum": "CT_1",
}
CHAIN_INDEX_TO_CANONICAL = {
    "501": "CT_501",
    "56": "56",
    "8453": "CT_8453",
    "1": "CT_1",
}


def canonical_chain_for_onchainos(chain_name: str, chain_index: Any = "") -> str:
    """Map onchainos --chain name (and optional chainIndex) to queue `chain` field."""
    key = (chain_name or "").strip().lower()
    if key in CHAIN_SLUG_TO_CANONICAL:
        return CHAIN_SLUG_TO_CANONICAL[key]
    idx = str(chain_index or "").strip()
    if idx in CHAIN_INDEX_TO_CANONICAL:
        return CHAIN_INDEX_TO_CANONICAL[idx]
    if key.isdigit():
        return key
    return key or "unknown"


def signal_chain_is_solana(sig: Dict[str, Any]) -> bool:
    """True if signal targets Solana mainnet (executor + monitor filter)."""
    c = str(sig.get("chain") or "")
    if c == "CT_501" or c.upper() == "CT_501":
        return True
    if c.lower() == "solana":
        return True
    idx = str(sig.get("chainIndex") or sig.get("chain_id") or "")
    return idx == "501"


def signal_chain_is_bsc(sig: Dict[str, Any]) -> bool:
    c = str(sig.get("chain") or "")
    return c == "56"


def okx_env_for_subprocess() -> Optional[Dict[str, str]]:
    """
    Build env for onchainos subprocess calls. Returns None if credentials missing
    (caller must skip or no-op — never embed secrets in code).
    """
    env = dict(os.environ)
    k = env.get("OKX_PROD_API_KEY") or env.get("OKX_API_KEY")
    s = env.get("OKX_PROD_SECRET_KEY") or env.get("OKX_SECRET_KEY")
    p = env.get("OKX_PROD_PASSPHRASE") or env.get("OKX_PASSPHRASE")
    if not (k and s and p):
        return None
    env["OKX_PROD_API_KEY"] = k
    env["OKX_PROD_SECRET_KEY"] = s
    env["OKX_PROD_PASSPHRASE"] = p
    env["OKX_API_KEY"] = k
    env["OKX_SECRET_KEY"] = s
    env["OKX_PASSPHRASE"] = p
    return env


def atomic_write_json(path: str, obj: Any, indent: int = 2) -> None:
    """Write JSON atomically (temp + replace) to reduce torn writes."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=d, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json_file(path: str, default: Any = None) -> Any:
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def lock_path_for(path: str) -> str:
    """Path to companion lock file for cross-process coordination."""
    return path + ".lock"


def _stale_lock_seconds() -> float:
    return float(os.environ.get("QCLAW_LOCK_STALE_SEC", "120"))


@contextmanager
def file_lock(lock_path: str, timeout_sec: float = 30.0) -> Iterator[None]:
    """
    Exclusive lock via O_CREAT|O_EXCL. Stale locks (mtime > threshold) are removed.
    Works on Windows without extra deps.
    """
    deadline = time.time() + timeout_sec
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            finally:
                os.close(fd)
            break
        except FileExistsError:
            if time.time() >= deadline:
                raise TimeoutError(f"lock timeout: {lock_path}")
            try:
                st = os.stat(lock_path)
                if time.time() - st.st_mtime > _stale_lock_seconds():
                    os.unlink(lock_path)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def locked_read_json(path: str, default: Any, timeout_sec: float = 30.0) -> Any:
    """Read JSON while holding exclusive lock (pair with locked_write_json)."""
    with file_lock(lock_path_for(path), timeout_sec=timeout_sec):
        return read_json_file(path, default=default)


def locked_write_json(
    path: str,
    obj: Any,
    indent: int = 2,
    timeout_sec: float = 30.0,
    before_write: Optional[Any] = None,
) -> None:
    """Write JSON atomically while holding exclusive lock. Optional before_write() callback."""
    with file_lock(lock_path_for(path), timeout_sec=timeout_sec):
        if callable(before_write):
            before_write()
        atomic_write_json(path, obj, indent=indent)


def dynamic_sl_tp_from_safety(
    safety_score: float,
    price_impact_pct: float = 0.0,
    base_sl: float = -0.08,
    base_tp: float = 0.12,
) -> Tuple[float, float, float]:
    """
    Returns (stop_loss_pct, take_profit_pct, position_scale).
    Higher risk (lower safety score / higher impact) -> wider SL, smaller size scale.
    """
    sl, tp, scale = base_sl, base_tp, 1.0
    imp = float(price_impact_pct or 0)
    sc = float(safety_score or 0)

    if imp >= 8:
        sl, tp, scale = -0.12, 0.15, 0.65
    elif imp >= 5:
        sl, tp, scale = -0.10, 0.13, 0.8
    elif imp >= 3:
        sl, tp, scale = -0.09, 0.125, 0.9

    if sc < 50 and sc >= 40:
        scale = min(scale, 0.85)
        sl = min(sl, -0.09)
    elif sc < 40:
        scale = min(scale, 0.7)
        sl = min(sl, -0.10)

    return sl, tp, max(0.5, min(1.0, scale))


def telegram_env() -> Tuple[str, str]:
    """Telegram credentials from environment only (no defaults)."""
    return os.environ.get("TG_BOT_TOKEN", ""), os.environ.get("TG_CHAT_ID", "")
