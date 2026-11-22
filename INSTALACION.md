# Instalación en un clic (`install.bat` y `run.bat`)

`install.bat` deja el entorno de desarrollo listo en Windows con un doble clic;
`run.bat` levanta la API. Ambos están en la raíz del repositorio.

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
| 3 | Instalar `torch` solo CPU | `pip install torch --index-url https://download.pytorch.org/whl/cpu` | Se salta si `torch` ya importa |
| 4 | Instalar dependencias | `.venv\Scripts\python -m pip install -r requirements.txt` | pip solo instala lo que falte |
| 5 | Crear `.env` | `copy .env.example .env` | **No se sobrescribe** (tiene datos de cada uno) |
| 6 | Generar `AUTH_SECRET` | Python: `secrets.token_urlsafe(48)` escrito en `.env` | Solo si está vacío o falta; nunca se reemplaza uno existente ni se muestra en pantalla |
| 7 | Generar la base | `.venv\Scripts\python -X utf8 db\generar_datos.py` | Solo si no existe `db\anticipa.db` (el script **borra** la base al recrearla) |
| 8 | Preparar el índice del RAG | `.venv\Scripts\python -X utf8 -m scripts.preparar_rag` | Descarga el modelo de embeddings (~195 MB) solo la primera vez. Si falla (sin red), avisa y sigue: la API usa TF-IDF |
| 9 | Verificar | `.venv\Scripts\python -m pytest -q` | — |
| 10 | Indicaciones finales | Mensaje en pantalla (ver abajo) | — |

### Detalles importantes
- **`torch` antes que el resto (paso 3):** si `requirements.txt` lo instala primero, pip
  baja la versión con CUDA (~2,5 GB). La de CPU pesa unos 200 MB y basta para los
  embeddings.
- **Orden 6 → 7:** `db/generar_datos.py` necesita `AUTH_SECRET` (guarda los códigos OTP
  de prueba con HMAC). Si se genera la base sin secreto, falla.
- **Cambiar `AUTH_SECRET` después** invalida las sesiones abiertas y los códigos
  pendientes, y los códigos de prueba de la base dejan de coincidir: hay que regenerar
  la base. Por eso el paso 6 nunca toca un secreto existente.
- **UTF-8:** el `.bat` hace `chcp 65001` y `PYTHONUTF8=1` para que tildes y eñes se
  vean bien (también en rutas como `C:\Users\Tomás\...`).
- **Errores:** si un paso falla, el script se detiene, dice cuál fue y no sigue.
- **Sin pausa (CI o pruebas):** definir `INSTALL_SIN_PAUSA=1` antes de ejecutarlo para
  que no espere una tecla al final.

## Indicación final (paso 10)

Lo que el script muestra al terminar:

> Entorno listo. Falta completar `.env` con tus datos:
> - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_REMITENTE`: correo
>   que envía el código OTP (con Gmail, una contraseña de aplicación).
> - `CORREO_PRUEBA_n` / `NOMBRE_PRUEBA_n`: tu correo en tu slot (1 a 5) para recibir el OTP.
> - `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`: cuando se conecte el chat.
>
> Después de cambiar `CORREO_PRUEBA_*`, regenera la base:
> `.venv\Scripts\python -X utf8 db\generar_datos.py`
>
> Levantar la API: `run.bat` (otro puerto: `run.bat 8001`) y abre
> http://127.0.0.1:8000/docs o http://127.0.0.1:8000/dev/rag (con `ENTORNO=dev`).

## `run.bat`

- Comprueba que existan `.venv` y `.env`; si no, pide ejecutar `install.bat`.
- Avisa si el puerto está ocupado (en vez del `Errno 10048` de uvicorn) y sugiere otro.
- Muestra las URL; `/dev/rag` solo si `ENTORNO=dev` (lo lee igual que la app).
- Levanta `uvicorn app.main:app` sin `--reload`. Para desarrollar con recarga:
  `.venv\Scripts\python -m uvicorn app.main:app --reload`.

## Pendiente (para trabajar luego)
- [x] `install.bat` en la raíz, probado en una copia limpia sin `.venv`, `.env` ni base.
- [x] `run.bat` que levanta la API usando `.venv`.
- [ ] Revisar la redacción de la indicación final y las variables que se piden.
- [ ] Actualizar la sección "Instalación" del README para apuntar a `install.bat`.
- [ ] Cuando existan `ENTORNO` y el límite por IP (pasos 4 y 5 de `PENDIENTES_auth.md`),
      decidir si el `.bat` debe avisar algo sobre ellos (tienen valores por defecto).
