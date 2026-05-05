# HEARTBEAT.md — Lightweight Version

## Purpose
Trading tasks are handled by Windows Task Scheduler (run_unified.ps1).  
Heartbeat should NOT run trading scripts — that wastes tokens.

## What to Check (keep it minimal)
1. Any critical alerts or user messages requiring immediate attention?
2. Any system issues (disk full, network down)?

## Rules
- If nothing urgent → reply exactly: `HEARTBEAT_OK`
- Do NOT run scalper scripts here — Task Scheduler handles that
- Do NOT check portfolio status here — wastes tokens
- Only alert if there's a real emergency

## Emergency Conditions (rare)
- User sent an urgent message in the last few minutes
- Disk space < 1GB
- Multiple consecutive task failures detected

Otherwise: HEARTBEAT_OK
