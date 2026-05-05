# run_signals.ps1 - THIN WRAPPER → launchers/run_signals.ps1
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
& $py "C:\Users\dell\.qclaw\workspace\scripts\active\signal_fetch_once.py" 2>&1
