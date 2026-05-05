@echo off
chcp 65001 >nul
cd /d "C:\Users\dell\.qclaw\workspace\scripts"
start /B pythonw.exe signal_listener.py >nul 2>&1
echo Signal listener started in background.
