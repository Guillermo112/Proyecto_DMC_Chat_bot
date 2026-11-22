@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

rem Uso: run.bat [puerto]    (por defecto 8000)
set "PUERTO=%~1"
if not defined PUERTO set "PUERTO=8000"

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (echo [ERROR] No existe .venv. Ejecuta primero install.bat. & goto :error)
if not exist ".env" (echo [ERROR] No existe .env. Ejecuta primero install.bat. & goto :error)

rem Puerto ocupado: avisar antes de que uvicorn falle con Errno 10048
netstat -ano | findstr /r /c:"127\.0\.0\.1:%PUERTO% .*LISTENING" /c:"0\.0\.0\.0:%PUERTO% .*LISTENING" >nul
if not errorlevel 1 (echo [ERROR] El puerto %PUERTO% ya esta en uso. Cierra el otro servidor o usa: run.bat 8001 & goto :error)

rem ENTORNO se lee igual que la app (variable del sistema o .env)
for /f "delims=" %%e in ('%VPY% -c "from app import config; print(config.ENTORNO)"') do set "ENTORNO_APP=%%e"
rem Bot de Telegram: activo solo si hay TELEGRAM_BOT_TOKEN (sin mostrar el token)
for /f "delims=" %%t in ('%VPY% -c "from app import config; print(('lista' if config.TELEGRAM_USUARIOS_PERMITIDOS else 'abierto') if config.TELEGRAM_BOT_TOKEN else 'no')"') do set "TELEGRAM_APP=%%t"

echo === API Anticipa en http://127.0.0.1:%PUERTO% ===
echo   Chat:               http://127.0.0.1:%PUERTO%/chat
echo   Documentacion:      http://127.0.0.1:%PUERTO%/docs
if /i "%ENTORNO_APP%"=="dev" (
    echo   Banco de pruebas:   http://127.0.0.1:%PUERTO%/dev/rag
    echo   ^(la primera busqueda tarda unos segundos: carga el indice^)
) else (
    echo   ENTORNO=%ENTORNO_APP%: /dev/rag y el CRUD /api no estan montados ^(usa ENTORNO=dev en .env^).
)
if /i "%TELEGRAM_APP%"=="lista" echo   Telegram:           bot activo, solo usuarios de TELEGRAM_USUARIOS_PERMITIDOS
if /i "%TELEGRAM_APP%"=="abierto" echo   Telegram:           bot activo y ABIERTO a cualquiera ^(define TELEGRAM_USUARIOS_PERMITIDOS^)
if /i "%TELEGRAM_APP%"=="no" echo   Telegram:           sin bot ^(TELEGRAM_BOT_TOKEN vacio en .env^)
echo   Para detenerla: Ctrl+C
echo.
"%VPY%" -m uvicorn app.main:app --port %PUERTO%
exit /b %errorlevel%

:error
echo.
pause
exit /b 1
