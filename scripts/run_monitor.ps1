# run_monitor.ps1 - THIN WRAPPER → active/monitor_positions.py
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
& $py "C:\Users\dell\.qclaw\workspace\scripts\active\monitor_positions.py" 2>&1 | Out-File -Append -Encoding UTF8 "C:\Users\dell\.qclaw\workspace\data\monitor-log.txt"
