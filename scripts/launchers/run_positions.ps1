$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
python "C:\Users\dell\.qclaw\workspace\scripts\scalper_positions.py" 2>&1 | Out-File -Append -Encoding UTF8 "C:\Users\dell\.qclaw\workspace\data\manager-log.txt"
