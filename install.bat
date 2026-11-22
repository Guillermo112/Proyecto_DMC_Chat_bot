@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo === Instalacion del entorno Anticipa ===

rem 1. Python >= 3.10 (prefiere 3.12)
set "PY="
py -3.12 -c "" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 -c "" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "" >nul 2>&1 && set "PY=python"
if not defined PY (echo [ERROR] No se encontro Python. Instala Python 3.12. & goto :error)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || (echo [ERROR] Se requiere Python 3.10 o superior. & goto :error)
echo [1/9] Python: & %PY% --version

rem 2. Entorno virtual
set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" (
    echo [2/9] .venv ya existe, se reutiliza.
) else (
    echo [2/9] Creando .venv...
    %PY% -m venv .venv || (echo [ERROR] No se pudo crear .venv. & goto :error)
)

rem 3. torch solo CPU, antes que el resto: si no, pip baja la version con CUDA (~2,5 GB)
"%VPY%" -c "import torch" >nul 2>&1
if errorlevel 1 (
    echo [3/9] Instalando torch solo CPU ^(unos 200 MB, puede tardar^)...
    "%VPY%" -m pip install --disable-pip-version-check -q "torch>=2.15,<3" --index-url https://download.pytorch.org/whl/cpu || (echo [ERROR] Fallo la instalacion de torch. & goto :error)
) else (
    echo [3/9] torch ya instalado.
)

rem 4. Dependencias
echo [4/9] Instalando dependencias...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || (echo [ERROR] Fallo pip install. & goto :error)

rem 5. .env desde la plantilla (nunca se sobrescribe)
if exist ".env" (
    echo [5/9] .env ya existe, no se modifica.
) else (
    copy /y ".env.example" ".env" >nul || (echo [ERROR] No se pudo copiar .env.example. & goto :error)
    echo [5/9] .env creado desde .env.example.
)

rem 6. AUTH_SECRET: solo si esta vacio o falta; no se muestra
"%VPY%" -c "import re,secrets,pathlib; p=pathlib.Path('.env'); s=p.read_text(encoding='utf-8-sig'); v=re.search(r'(?m)^AUTH_SECRET=(.*)$', s); n='AUTH_SECRET='+secrets.token_urlsafe(48); ok=v and v.group(1).strip(); s=s if ok else (re.sub(r'(?m)^AUTH_SECRET=.*$', lambda m: n, s) if v else s.rstrip('\n')+'\n'+n+'\n'); p.write_text(s, encoding='utf-8'); print('[6/9] AUTH_SECRET ya estaba definido, no se modifica.' if ok else '[6/9] AUTH_SECRET generado en .env.')" || (echo [ERROR] No se pudo escribir AUTH_SECRET. & goto :error)

rem 7. Base de datos (solo si no existe: generar_datos.py la borra al recrearla)
if exist "db\anticipa.db" (
    echo [7/9] db\anticipa.db ya existe, no se regenera.
) else (
    echo [7/9] Generando db\anticipa.db...
    "%VPY%" -X utf8 db\generar_datos.py >nul || (echo [ERROR] Fallo la generacion de la base. & goto :error)
)

rem 8. Indice del RAG: descarga el modelo de embeddings (~195 MB, una vez)
rem    Si falla (sin red), se avisa y se sigue: la API cae a TF-IDF.
echo [8/9] Preparando el indice del RAG ^(la primera vez descarga ~195 MB^)...
"%VPY%" -X utf8 -m scripts.preparar_rag || echo [AVISO] No se pudo preparar el indice. La API usara TF-IDF hasta que vuelvas a ejecutar install.bat con red.

rem 9. Verificacion
echo [9/9] Ejecutando pruebas...
"%VPY%" -m pytest -q -p no:cacheprovider || (echo [ERROR] Fallaron pruebas. & goto :error)

echo.
echo ============================================================
echo  Entorno listo. Paso siguiente: completa .env con tus datos:
echo   - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_REMITENTE
echo     (correo que envia el OTP; con Gmail, contrasena de aplicacion)
echo   - CORREO_PRUEBA_n / NOMBRE_PRUEBA_n: tu correo en tu slot (1 a 5)
echo   - LLM_BASE_URL, LLM_API_KEY, LLM_MODEL: cuando se conecte el chat
echo.
echo  Despues, ejecuta regenerar_base.bat: la base se creo antes de
echo  que pusieras tu correo, y sin eso el codigo OTP no te llega.
echo.
echo  Luego levanta la API:  run.bat   (otro puerto: run.bat 8001)
echo    http://127.0.0.1:8000/docs
echo    http://127.0.0.1:8000/dev/rag   (banco de pruebas, con ENTORNO=dev)
echo.
echo  Guia completa ^(que hacer y cuando^): README.md
echo ============================================================
if not defined INSTALL_SIN_PAUSA pause
exit /b 0

:error
echo.
echo La instalacion se detuvo. Revisa el mensaje de arriba.
if not defined INSTALL_SIN_PAUSA pause
exit /b 1
