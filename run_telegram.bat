@echo off
setlocal
rem Uso: run_telegram.bat [puerto]    (por defecto 8000)
rem Levanta la API CON el bot de Telegram (necesita TELEGRAM_BOT_TOKEN en .env).
rem Un token admite un solo lector: si otra API de esta PC ya tiene el bot, esta
rem arranca sin bot y lo avisa. Entre PC distintas, cada integrante usa su propio bot.
set "TELEGRAM_ACTIVO=1"
call "%~dp0run.bat" %*
exit /b %errorlevel%
