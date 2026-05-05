# run_health.ps1 - API Health Check Launcher
# Called every 5 min by SmartMoneyHealth Task Scheduler
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
& $py "C:\Users\dell\.qclaw\workspace\scripts\active\api_health_check.py"
