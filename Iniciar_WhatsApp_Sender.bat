@echo off
chcp 65001 >nul
title WhatsApp Sender Engine - Disparador WhatsApp
cd /d "%~dp0"

echo ========================================================
echo   WHATSAPP SENDER ENGINE - DISPARADOR PROFISSIONAL
echo ========================================================
echo.
echo [1/2] Abrindo painel visual no seu navegador...
start "" http://127.0.0.1:8765

echo [2/2] Iniciando motor de automacao e servidor local...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
