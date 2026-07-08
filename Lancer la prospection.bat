@echo off
title Skaelia - Prospection
cd /d "%~dp0"
start "" http://localhost:5173
"C:\Users\gabin\AppData\Local\Programs\Python\Python312\python.exe" server.py
pause
