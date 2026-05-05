# run_scalper.ps1 - Scalper Orchestrator Launcher
# Called by SmartMoneyUnified Task Scheduler (DISABLED - backtest only)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
& $py "C:\Users\dell\.qclaw\workspace\scripts\active\scalper_orchestrator.py" 2>&1 | Out-File -Append -Encoding UTF8 "C:\Users\dell\.qclaw\workspace\data\scalper-log.txt"
