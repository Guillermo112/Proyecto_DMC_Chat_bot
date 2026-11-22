# Instalación en un clic (`install.bat`)

Plan de lo que debe hacer `install.bat` para dejar el entorno de desarrollo listo en
Windows con un doble clic. Al final hay un borrador del `.bat` ya probado en una
copia limpia del repositorio.

## Requisitos previos (no los instala el `.bat`)
- **Git** (para clonar el repositorio).
- **Python 3.10 o superior**; se recomienda **3.12**. El código usa `X | None`, que
  requiere 3.10. Con versiones muy nuevas (3.14+) puede que alguna dependencia aún no
  tenga paquete precompilado.
- Ejecutar el `.bat` desde la raíz del proyecto (doble clic en el Explorador funciona:
  el script se ubica solo con `cd /d "%~dp0"`).

## Pasos

Todos los pasos se pueden repetir sin romper nada: si algo ya existe, se salta.

| # | Paso | Comando | Si ya existe |
|---|---|---|---|
| 1 | Elegir Python ≥ 3.10 | `py -3.12`, si no `py -3`, si no `python` | — |
| 2 | Crear entorno virtual | `python -m venv .venv` | Se reutiliza `.venv` |
| 3 | Instalar dependencias | `.venv\Scripts\python -m pip install -r requirements.txt` | pip solo instala lo que falte |
| 4 | Crear `.env` | `copy .env.example .env` | **No se sobrescribe** (tiene datos de cada uno) |
| 5 | Generar `AUTH_SECRET` | Python: `secrets.token_urlsafe(48)` escrito en `.env` | Solo si está vacío o falta; nunca se reemplaza uno existente ni se muestra en pantalla |
| 6 | Generar la base | `.venv\Scripts\python -X utf8 db\generar_datos.py` | Solo si no existe `db\anticipa.db` (el script **borra** la base al recrearla) |
| 7 | Verificar | `.venv\Scripts\python -m pytest -q` | — |
| 8 | Indicaciones finales | Mensaje en pantalla (ver abajo) | — |

### Detalles importantes
- **Orden 5 → 6:** `db/generar_datos.py` necesita `AUTH_SECRET` (guarda los códigos OTP
  de prueba con HMAC). Si se genera la base sin secreto, falla.
- **Cambiar `AUTH_SECRET` después** invalida las sesiones abiertas y los códigos
  pendientes, y los códigos de prueba de la base dejan de coincidir: hay que regenerar
  la base. Por eso el paso 5 nunca toca un secreto existente.
- **UTF-8:** el `.bat` hace `chcp 65001` y `PYTHONUTF8=1` para que tildes y eñes se
  vean bien (también en rutas como `C:\Users\Tomás\...`).
- **Errores:** si un paso falla, el script se detiene, dice cuál fue y no sigue.
- **Sin pausa (CI o pruebas):** definir `INSTALL_SIN_PAUSA=1` antes de ejecutarlo para
  que no espere una tecla al final.

## Indicación final (paso 8)

Lo que el script muestra al terminar:

> Entorno listo. Falta completar `.env` con tus datos:
> - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_REMITENTE`: correo
>   que envía el código OTP (con Gmail, una contraseña de aplicación).
> - `CORREO_PRUEBA_n` / `NOMBRE_PRUEBA_n`: tu correo en tu slot (1 a 5) para recibir el OTP.
>
> Después de cambiar `CORREO_PRUEBA_*`, regenera la base:
> `.venv\Scripts\python -X utf8 db\generar_datos.py`
>
> Para levantar la API: `.venv\Scripts\python -m uvicorn app.main:app --reload`
> y abre http://127.0.0.1:8000/docs

## Pendiente (para trabajar luego)
- [ ] Pasar el borrador a `install.bat` en la raíz y probarlo en una máquina sin `.venv`.
- [ ] Revisar la redacción de la indicación final y las variables que se piden.
- [ ] Opcional: `run.bat` que solo levante la API (`uvicorn`) usando `.venv`.
- [ ] Actualizar la sección "Instalación" del README para apuntar a `install.bat`.
- [ ] Cuando existan `ENTORNO` y el límite por IP (pasos 4 y 5 de `PENDIENTES_auth.md`),
      decidir si el `.bat` debe avisar algo sobre ellos (tienen valores por defecto).

## Borrador de `install.bat`

```bat
@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo === Instalacion del entorno AnticIpA ===

rem 1. Python >= 3.10 (prefiere 3.12)
set "PY="
py -3.12 -c "" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 -c "" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "" >nul 2>&1 && set "PY=python"
if not defined PY (echo [ERROR] No se encontro Python. Instala Python 3.12. & goto :error)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || (echo [ERROR] Se requiere Python 3.10 o superior. & goto :error)
echo [1/7] Python: & %PY% --version

rem 2. Entorno virtual
set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" (
    echo [2/7] .venv ya existe, se reutiliza.
) else (
    echo [2/7] Creando .venv...
    %PY% -m venv .venv || (echo [ERROR] No se pudo crear .venv. & goto :error)
)

rem 3. Dependencias
echo [3/7] Instalando dependencias...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || (echo [ERROR] Fallo pip install. & goto :error)

rem 4. .env desde la plantilla (nunca se sobrescribe)
if exist ".env" (
    echo [4/7] .env ya existe, no se modifica.
) else (
    copy /y ".env.example" ".env" >nul || (echo [ERROR] No se pudo copiar .env.example. & goto :error)
    echo [4/7] .env creado desde .env.example.
)

rem 5. AUTH_SECRET: solo si esta vacio o falta; no se muestra
"%VPY%" -c "import re,secrets,pathlib; p=pathlib.Path('.env'); s=p.read_text(encoding='utf-8-sig'); v=re.search(r'(?m)^AUTH_SECRET=(.*)$', s); n='AUTH_SECRET='+secrets.token_urlsafe(48); ok=v and v.group(1).strip(); s=s if ok else (re.sub(r'(?m)^AUTH_SECRET=.*$', lambda m: n, s) if v else s.rstrip('\n')+'\n'+n+'\n'); p.write_text(s, encoding='utf-8'); print('[5/7] AUTH_SECRET ya estaba definido, no se modifica.' if ok else '[5/7] AUTH_SECRET generado en .env.')" || (echo [ERROR] No se pudo escribir AUTH_SECRET. & goto :error)

rem 6. Base de datos (solo si no existe: generar_datos.py la borra al recrearla)
if exist "db\anticipa.db" (
    echo [6/7] db\anticipa.db ya existe, no se regenera.
) else (
    echo [6/7] Generando db\anticipa.db...
    "%VPY%" -X utf8 db\generar_datos.py >nul || (echo [ERROR] Fallo la generacion de la base. & goto :error)
)

rem 7. Verificacion
echo [7/7] Ejecutando pruebas...
"%VPY%" -m pytest -q -p no:cacheprovider || (echo [ERROR] Fallaron pruebas. & goto :error)

echo.
echo ============================================================
echo  Entorno listo. Falta completar .env con tus datos:
echo   - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_REMITENTE
echo     (correo que envia el OTP; con Gmail, contrasena de aplicacion)
echo   - CORREO_PRUEBA_n / NOMBRE_PRUEBA_n: tu correo en tu slot (1 a 5)
echo.
echo  Despues de cambiar CORREO_PRUEBA_*, regenera la base:
echo    .venv\Scripts\python -X utf8 db\generar_datos.py
echo.
echo  Levantar la API:
echo    .venv\Scripts\python -m uvicorn app.main:app --reload
echo    http://127.0.0.1:8000/docs
echo ============================================================
if not defined INSTALL_SIN_PAUSA pause
exit /b 0

:error
echo.
echo La instalacion se detuvo. Revisa el mensaje de arriba.
if not defined INSTALL_SIN_PAUSA pause
exit /b 1
```
