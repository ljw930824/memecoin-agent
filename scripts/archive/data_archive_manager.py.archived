#!/usr/bin/env python3
"""
data_archive_manager.py - 数据归档管理器

策略:
  - backup files: 24h内全保留, 24h-7d保留每小时1个, 7d-30d保留每天1个, >30d删除
  - closed positions: 清仓后移入归档文件夹
  - wallet snapshots: 仅保留当前版本，旧版本按日期归档
  - logs: 保留30天热数据

用法:
  python data_archive_manager.py              # 运行归档
  python data_archive_manager.py --dry-run    # 预览模式
  python data_archive_manager.py --status     # 查看归档状态
"""

import os
import json
import shutil
import re
import glob
import sys
from datetime import datetime, timedelta
from collections import defaultdict

DATA_DIR = os.path.expanduser("~/.qclaw/workspace/data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
BACKUP_DIR = os.path.join(ARCHIVE_DIR, "backups")
POSITIONS_DIR = os.path.join(ARCHIVE_DIR, "closed_positions")
WALLETS_DIR = os.path.join(ARCHIVE_DIR, "wallet_snapshots")
LOGS_DIR = os.path.join(ARCHIVE_DIR, "logs")


def ensure_dirs():
    for d in [ARCHIVE_DIR, BACKUP_DIR, POSITIONS_DIR, WALLETS_DIR, LOGS_DIR]:
        os.makedirs(d, exist_ok=True)


def parse_backup_ts(filename):
    """Parse timestamp from smart-money-state_bak_YYYYMMDD_HHMMSS.json"""
    match = re.search(r"(\d{8})_(\d{6})", filename)
    if match:
        try:
            return datetime.strptime(
                match.group(1) + "_" + match.group(2), "%Y%m%d_%H%M%S"
            )
        except ValueError:
            pass
    return None


def decay_backups(now=None, dry_run=False):
    """Time-decay smart-money-state_bak_* files

    Rules:
      <24h: keep all
      24h-7d: keep 1 per hour (latest)
      7d-30d: keep 1 per day (latest)
      >30d: remove (archived first)
    """
    if now is None:
        now = datetime.now()

    pattern = os.path.join(DATA_DIR, "smart-money-state_bak_*.json")
    files = glob.glob(pattern)

    file_entries = []
    for fp in files:
        ts = parse_backup_ts(os.path.basename(fp))
        if ts:
            file_entries.append((ts, fp))

    if not file_entries:
        return {"removed": 0, "kept": 0, "archived": 0}

    file_entries.sort()

    removed = 0
    kept = 0
    archived = 0
    hourly_kept = set()
    daily_kept = set()

    for ts, fp in file_entries:
        age = now - ts

        if age.total_seconds() < 86400:  # <24h
            kept += 1
            continue

        elif age.days < 7:  # 24h-7d: keep hourly
            hour_key = ts.strftime("%Y%m%d_%H")
            if hour_key not in hourly_kept:
                hourly_kept.add(hour_key)
                kept += 1
            else:
                dest = os.path.join(BACKUP_DIR, os.path.basename(fp))
                if not os.path.exists(dest) and not dry_run:
                    shutil.copy2(fp, dest)
                archived += 1
                if not dry_run:
                    os.remove(fp)
                removed += 1

        elif age.days < 30:  # 7d-30d: keep daily
            day_key = ts.strftime("%Y%m%d")
            if day_key not in daily_kept:
                daily_kept.add(day_key)
                kept += 1
            else:
                dest = os.path.join(BACKUP_DIR, os.path.basename(fp))
                if not os.path.exists(dest) and not dry_run:
                    shutil.copy2(fp, dest)
                archived += 1
                if not dry_run:
                    os.remove(fp)
                removed += 1

        else:  # >30d
            dest = os.path.join(BACKUP_DIR, os.path.basename(fp))
            if not os.path.exists(dest) and not dry_run:
                shutil.copy2(fp, dest)
            archived += 1
            if not dry_run:
                os.remove(fp)
            removed += 1

    return {"removed": removed, "kept": kept, "archived": archived}


def archive_closed_positions(state_file=None, dry_run=False):
    """Move closed positions from state file to daily archive files

    Returns positions archived and clears them from state.
    """
    if state_file is None:
        state_file = os.path.join(DATA_DIR, "sm_monitor_state.json")

    if not os.path.exists(state_file):
        return {"moved": 0, "reason": "no state file"}

    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)

    closed = state.get("closed_positions", [])

    if not closed:
        return {"moved": 0, "reason": "no closed positions"}

    # Group by sell date
    by_date = defaultdict(list)
    for pos in closed:
        sell_time = pos.get("last_sell_time", pos.get("buy_time", "unknown"))
        if isinstance(sell_time, str) and len(sell_time) >= 10:
            date_key = sell_time[:10]
        else:
            date_key = "unknown"
        by_date[date_key].append(pos)

    moved = 0
    for date_key, pos_list in by_date.items():
        archive_file = os.path.join(POSITIONS_DIR, f"closed_{date_key}.json")

        # Merge with existing archive (dedup by token_address)
        existing = []
        if os.path.exists(archive_file):
            with open(archive_file, "r", encoding="utf-8") as f:
                existing = json.load(f)

        existing_addrs = {p.get("token_address") for p in existing}
        new_positions = [
            p for p in pos_list if p.get("token_address") not in existing_addrs
        ]

        if new_positions:
            existing.extend(new_positions)
            if not dry_run:
                with open(archive_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
            moved += len(new_positions)

    # Clear from state
    if moved > 0 and not dry_run:
        state["closed_positions"] = []
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    return {"moved": moved, "dates": list(by_date.keys())}


def archive_wallet_snapshot(wallet_file=None):
    """Snapshot current wallet file if changed, decay old snapshots"""
    if wallet_file is None:
        wallet_file = os.path.join(DATA_DIR, "sm_wallets.json")

    if not os.path.exists(wallet_file):
        return {"action": "skipped", "reason": "no file"}

    # Check if changed since last snapshot
    existing_snapshots = sorted(
        glob.glob(os.path.join(WALLETS_DIR, "sm_wallets_*.json"))
    )
    if existing_snapshots:
        last = existing_snapshots[-1]
        with open(last, "rb") as f:
            last_hash = hash(f.read())
        with open(wallet_file, "rb") as f:
            current_hash = hash(f.read())
        if last_hash == current_hash:
            return {"action": "skipped", "reason": "unchanged"}

    # Create snapshot
    now = datetime.now()
    snapshot_name = f"sm_wallets_{now.strftime('%Y%m%d_%H%M%S')}.json"
    dest = os.path.join(WALLETS_DIR, snapshot_name)
    shutil.copy2(wallet_file, dest)

    # Decay old snapshots
    all_snaps = sorted(glob.glob(os.path.join(WALLETS_DIR, "sm_wallets_*.json")))
    removed = 0
    if len(all_snaps) > 1:
        hourly_kept = set()
        daily_kept = set()
        for snap in all_snaps[:-1]:  # Don't touch newest
            ts = parse_backup_ts(os.path.basename(snap))
            if ts:
                age = now - ts
                if age.total_seconds() < 86400:
                    pass  # keep all <24h
                elif age.days < 7:
                    hour_key = ts.strftime("%Y%m%d_%H")
                    if hour_key in hourly_kept:
                        os.remove(snap)
                        removed += 1
                    else:
                        hourly_kept.add(hour_key)
                elif age.days < 30:
                    day_key = ts.strftime("%Y%m%d")
                    if day_key in daily_kept:
                        os.remove(snap)
                        removed += 1
                    else:
                        daily_kept.add(day_key)
                else:
                    os.remove(snap)
                    removed += 1

    return {"action": "snapshot", "file": snapshot_name, "old_removed": removed}


def load_closed_positions(token_address=None, chain=None, date_from=None, date_to=None):
    """Load archived closed positions - for backtest use"""
    results = []
    pattern = os.path.join(POSITIONS_DIR, "closed_*.json")

    for fp in sorted(glob.glob(pattern)):
        basename = os.path.basename(fp)
        date_match = re.search(r"closed_(\d{4}-\d{2}-\d{2})", basename)
        if date_match:
            date_key = date_match.group(1)
            if date_from and date_key < date_from:
                continue
            if date_to and date_key > date_to:
                continue

        with open(fp, "r", encoding="utf-8") as f:
            positions = json.load(f)

        for pos in positions:
            if token_address and pos.get("token_address") != token_address:
                continue
            if chain and pos.get("chain") != chain:
                continue
            results.append(pos)

    return results


def get_status():
    """Get archive status summary"""
    status = {}

    # Backup files
    pattern = os.path.join(DATA_DIR, "smart-money-state_bak_*.json")
    baks = glob.glob(pattern)
    status["backup_files"] = len(baks)
    status["backup_size_mb"] = round(
        sum(os.path.getsize(f) for f in baks) / 1024 / 1024, 1
    )

    # Archive
    if os.path.exists(ARCHIVE_DIR):
        for name, path in [
            ("archive_backups", BACKUP_DIR),
            ("closed_positions", POSITIONS_DIR),
            ("wallet_snapshots", WALLETS_DIR),
        ]:
            if os.path.exists(path):
                files = []
                for dp, dn, fns in os.walk(path):
                    files.extend(fns)
                status[f"{name}_count"] = len(files)
                total = sum(
                    os.path.getsize(os.path.join(dp, fn))
                    for dp, dn, fns in os.walk(path)
                    for fn in fns
                )
                status[f"{name}_size_mb"] = round(total / 1024 / 1024, 1)

    # Closed positions in archive
    if os.path.exists(POSITIONS_DIR):
        closed_files = glob.glob(os.path.join(POSITIONS_DIR, "closed_*.json"))
        total_positions = 0
        for fp in closed_files:
            with open(fp, "r", encoding="utf-8") as f:
                total_positions += len(json.load(f))
        status["archived_positions"] = total_positions

    # Total data dir
    total_files = sum(len(fns) for dp, dn, fns in os.walk(DATA_DIR))
    total_size = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, dn, fns in os.walk(DATA_DIR)
        for fn in fns
    )
    status["total_data_files"] = total_files
    status["total_data_size_mb"] = round(total_size / 1024 / 1024, 1)

    return status


def run_full_archive(dry_run=False):
    """Run all archive operations"""
    ensure_dirs()

    results = {"timestamp": datetime.now().isoformat(), "dry_run": dry_run}

    # 1. Decay backups
    print("[1] Decaying backup files...")
    r = decay_backups(dry_run=dry_run)
    results["backups"] = r
    print(f"    Kept: {r['kept']}, Removed: {r['removed']}, Archived: {r['archived']}")

    # 2. Archive closed positions
    print("[2] Archiving closed positions...")
    r = archive_closed_positions(dry_run=dry_run)
    results["positions"] = r
    print(f"    Moved: {r['moved']}")

    # 3. Snapshot wallet file
    print("[3] Snapshotting wallet file...")
    r = archive_wallet_snapshot()
    results["wallet"] = r
    print(f"    Action: {r['action']}")

    # 4. Report
    print("\n[4] Status after archiving:")
    status = get_status()
    results["status"] = status
    print(f"    data/: {status['total_data_files']} files, {status['total_data_size_mb']}MB")
    print(f"    backups: {status.get('backup_files', 0)} files, {status.get('backup_size_mb', 0)}MB")
    if "archive_backups_count" in status:
        print(f"    archive/backups/: {status['archive_backups_count']} files")
    if "archived_positions" in status:
        print(f"    archive/closed_positions/: {status['archived_positions']} positions")

    return results


# --- Integration API for sim/monitor ---

_auto_archive_counter = 0


def auto_archive(state_file=None, decay_interval=12):
    """Lightweight auto-archive, called by monitor every cycle (5min).
    decay_interval=12 means decay runs hourly (12 * 5min)."""
    global _auto_archive_counter
    _auto_archive_counter += 1
    ensure_dirs()
    result = {}

    r = archive_closed_positions(state_file=state_file)
    if r['moved'] > 0:
        result['positions_archived'] = r['moved']

    if _auto_archive_counter % decay_interval == 0:
        r = decay_backups()
        if r['removed'] > 0:
            result['backups_decayed'] = r
        r = archive_wallet_snapshot()
        if r['action'] == 'snapshot':
            result['wallet_snapshot'] = r['file']

    return result if result else None


def on_sell_closed(position_data, state_file=None):
    """Call when a position is fully sold. Adds to daily archive."""
    ensure_dirs()
    sell_time = position_data.get('last_sell_time', position_data.get('buy_time', 'unknown'))
    if isinstance(sell_time, str) and len(sell_time) >= 10:
        date_key = sell_time[:10]
    else:
        date_key = datetime.now().strftime('%Y-%m-%d')

    archive_file = os.path.join(POSITIONS_DIR, f'closed_{date_key}.json')
    existing = []
    if os.path.exists(archive_file):
        with open(archive_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    existing_addrs = {p.get('token_address') for p in existing}
    if position_data.get('token_address') not in existing_addrs:
        existing.append(position_data)
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return True
    return False


# --- CLI ---

if __name__ == "__main__":
    if "--status" in sys.argv:
        ensure_dirs()
        status = get_status()
        print(json.dumps(status, indent=2))
    else:
        dry_run = "--dry-run" in sys.argv
        if dry_run:
            print("=== DRY RUN MODE ===\n")
        results = run_full_archive(dry_run=dry_run)

        log_file = os.path.join(ARCHIVE_DIR, "last_archive_run.json")
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to {log_file}")
