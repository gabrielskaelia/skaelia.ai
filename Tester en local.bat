@echo off
title Skaelia - Test local (http://localhost:5173)
cd /d "%~dp0"

echo ================================================
echo   Skaelia - Prospection : test en local
echo ================================================
echo.
echo   Le site EN LIGNE est sur https://ai.skaelia.com (serveur OVH, 24h/24).
echo   Cette fenetre lance seulement une copie LOCALE pour tester tes modifs
echo   avant de faire "git push".
echo.
echo Demarrage de l'application locale...
start "" http://localhost:5173
"C:\Users\gabin\AppData\Local\Programs\Python\Python312\python.exe" server.py

echo.
echo Application arretee. (Ferme cette fenetre.)
pause
