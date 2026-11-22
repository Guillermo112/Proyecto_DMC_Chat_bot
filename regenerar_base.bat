@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

rem Uso: regenerar_base.bat [--publico]
rem   Borra y vuelve a crear db\anticipa.db con los correos de prueba de tu .env.
rem   --publico: ignora los CORREO_PRUEBA_* (todos los correos quedan en .example).
rem   REGENERAR_SIN_CONFIRMAR=1 evita la pregunta (pruebas automaticas).

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (echo [ERROR] No existe .venv. Ejecuta primero install.bat. & goto :error)
if not exist ".env" (echo [ERROR] No existe .env. Ejecuta primero install.bat. & goto :error)

echo === Regenerar la base de datos ===
echo Se BORRA db\anticipa.db y se crea de nuevo con datos fijos.
echo Se pierden los casos y mensajes que hayas registrado al probar.
echo Si run.bat esta abierto, detenlo antes (Ctrl+C).
echo.
if not defined REGENERAR_SIN_CONFIRMAR (
    choice /c SN /m "Continuar"
    if errorlevel 2 (echo Cancelado. & goto :fin)
)

echo Generando la base...
"%VPY%" -X utf8 db\generar_datos.py %1 > db\generar_datos.log 2>&1
if errorlevel 1 (
    type db\generar_datos.log
    echo.
    echo [ERROR] No se pudo generar la base. Causas comunes: run.bat abierto ^(base en uso^)
    echo         o AUTH_SECRET vacio en .env ^(ejecuta install.bat^). Detalle arriba.
    goto :error
)
echo Base creada. Validaciones en verde ^(detalle en db\generar_datos.log^).
echo.
echo Clientes de prueba para el OTP ^(el codigo llega al correo de cada uno^):
"%VPY%" -c "import sqlite3; c=sqlite3.connect('file:db/anticipa.db?mode=ro', uri=True); [print(f'  cliente {i:>2}  RUC {r}  ->  {m}') for i, r, m in c.execute('SELECT id_cliente, ruc, correo_facturacion FROM cliente WHERE id_cliente <= 13 ORDER BY id_cliente')]"
echo.
echo Los que terminan en .example no reciben correo: pon tu correo en tu slot
echo CORREO_PRUEBA_n del .env y vuelve a ejecutar regenerar_base.bat.

:fin
if not defined REGENERAR_SIN_CONFIRMAR pause
exit /b 0

:error
echo.
if not defined REGENERAR_SIN_CONFIRMAR pause
exit /b 1
