@echo off
title Skaelia - Site en ligne (croisia.me)
cd /d "%~dp0"
set PROSPECTION_PUBLIC=1

echo ================================================
echo   Skaelia - Mise en ligne du site croisia.me
echo ================================================
echo.
echo Demarrage de l'application...
start "Skaelia - Application" "C:\Users\gabin\AppData\Local\Programs\Python\Python312\python.exe" server.py

echo Attente du demarrage...
timeout /t 4 /nobreak >nul

echo Ouverture du tunnel vers croisia.me...
echo.
echo   -> Le site est accessible sur https://croisia.me
echo   -> Laisse cette fenetre OUVERTE tant que tu veux que le site soit en ligne.
echo   -> Ferme cette fenetre pour mettre le site hors ligne.
echo.
"C:\Users\gabin\AppData\Local\cloudflared\cloudflared.exe" tunnel --config "C:\Users\gabin\.cloudflared\config.yml" run skaelia-prospection

echo.
echo Tunnel arrete. Le site est hors ligne.
pause
