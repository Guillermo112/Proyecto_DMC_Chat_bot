@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

rem Uso: clientes_prueba.bat              los 13 clientes de prueba
rem      clientes_prueba.bat 3            solo los de tu slot (1 a 5)
rem      clientes_prueba.bat copiar 1     copia el RUC del cliente 1 al portapapeles
rem Solo lee la base: no cambia nada.

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (echo [ERROR] No existe .venv. Ejecuta primero install.bat. & goto :fin)

"%VPY%" -X utf8 -m scripts.clientes_prueba %*

:fin
rem Con doble clic la ventana se cerraria sin dejar leer: se pausa solo en ese caso.
echo %cmdcmdline% | find /i "%~nx0" >nul && pause
exit /b
