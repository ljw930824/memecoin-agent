#!/usr/bin/env python3
"""
scalper_orchestrator.py - Scalping Orchestrator
Relies on signal_listener.py for signal scanning (saves to signal-queue.json).
Only executes trades — no duplicate scanning.
"""
import sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import execute_bsc
import execute_solana


def main():
    print(f"\n{'#'*60}")
    print(f"# SCALPER ORCHESTRATOR  |  Execute Only (no scan)")
    print(f"# {'='*56}")

    # 1. BSC execution
    print(f"\n{'='*60}")
    print(f" Running: BSC Trader")
    print(f"{'='*60}")
    rc_bsc = execute_bsc.main()
    print(f"  Exit code: {rc_bsc}")

    # 2. Solana execution
    print(f"\n{'='*60}")
    print(f" Running: Solana Trader")
    print(f"{'='*60}")
    rc_sol = execute_solana.main()
    print(f"  Exit code: {rc_sol}")

    print(f"\n{'#'*60}")
    print(f"# DONE | BSC={rc_bsc} | Solana={rc_sol}")
    print(f"{'#'*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
