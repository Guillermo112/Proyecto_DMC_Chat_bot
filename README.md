# Anticipa: chatbot de facturación

Asistente virtual de facturación para los clientes empresa (B2B) de una empresa de
telecomunicaciones. Backend en Python + FastAPI sobre una base SQLite con datos
ficticios. Miniproyecto de certificación.

**Este README es la guía de referencia**: qué es el proyecto, qué `.bat` ejecutar y
cuándo, qué poner en tu `.env` y qué hacer después de cada cambio.

## Índice

1. [Objetivo](#objetivo)
2. [Los scripts `.bat`](#los-scripts-bat)
3. [Primera vez](#primera-vez)
4. [Día a día](#día-a-día)
5. [Cuándo hacer qué](#cuándo-hacer-qué)
6. [Variables de entorno (`.env`)](#variables-de-entorno-env)
7. [Instalación manual (sin `.bat`, Linux o macOS)](#instalación-manual-sin-bat-linux-o-macos)
8. [Estructura del proyecto](#estructura-del-proyecto)
9. [Referencia: identificación, API, RAG y datos](#referencia)

---

## Objetivo

**Qué hace Anticipa.** Explica facturas, consumos, tarifas, averías y solicitudes con
los datos reales del cliente; detecta cobros que no corresponden (facturas duplicadas,
servicios dados de baja que se siguen cobrando, tarifas distintas a las pactadas,
excesos sin sustento, compensaciones por SLA); y cuando encuentra algo, **registra el
caso y lo deriva al ejecutivo de cuenta**. Así evita que una duda de facturación
termine en un reclamo formal.

**Alcance: solo modo A.** El agente informa, explica, registra y deriva. No calcula
ajustes, no emite notas de crédito ni aplica gestos comerciales (eso es el modo B,
fuera de alcance por decisión del equipo; ver "Alcance" en
[`docs/capa_datos.md`](docs/capa_datos.md)).

**Quién responde qué.**

| Parte | Responde | Fuente |
|---|---|---|
| Herramientas (API `/mi`, `app/data`) | Todo dato del cliente: montos, fechas, estados, anomalías, solicitudes, casos | Base SQLite, filtrada por el cliente de la sesión |
| RAG (`app/rag`) | Conocimiento general: políticas, glosario, catálogo, tono | PDF de `docs/` y `catalogo.json` |

El RAG **nunca** es fuente de un monto, una fecha o un estado del cliente.

**Estado.**

| Hecho | Pendiente |
|---|---|
| Base de datos con las casuísticas CS-01 a CS-13 | Alinear `faq.json` con el modo A y su clasificador |
| Identificación por RUC + código OTP al correo | Evaluación por casuística y calibración del umbral |
| API del cliente autenticado (`/mi/...`) | Bot de Telegram (opcional) |
| RAG con filtro de modo A y banco de pruebas web (`/dev/rag`) | |
| Chat web (`/chat`) con herramientas, RAG y panel de traza | |

Detalle de lo pendiente: [`PENDIENTES_rag.md`](PENDIENTES_rag.md).

---

## Los scripts `.bat`

Cuatro scripts en la raíz, para Windows. Se ejecutan con doble clic o desde una
terminal en la carpeta del proyecto.

| Script | Objetivo | Cuándo |
|---|---|---|
| `install.bat` | Dejar el entorno listo: Python, dependencias, `.env`, secreto, base, índice del RAG y pruebas | La primera vez, y después de un `git pull` que cambie `requirements.txt` |
| `regenerar_base.bat` | Borrar y volver a crear `db\anticipa.db` con los correos de tu `.env` | Después de poner tu correo en `.env`, y cuando cambie la base en el repositorio |
| `run.bat` | Levantar la API para probarla | Cada vez que quieras usar la API o el banco de pruebas |
| `clientes_prueba.bat` | Ver los RUC de prueba, su casuística y a qué correo llega el código | Cuando necesites un RUC para probar (identificación, `/docs`, el chat) |

### `install.bat`

Prepara todo lo necesario para trabajar. **Se puede repetir sin romper nada**: lo que
ya existe se salta, y nunca sobrescribe tu `.env`, tu `AUTH_SECRET` ni tu base.

1. Busca Python 3.12 (o cualquier 3.10 o superior).
2. Crea el entorno virtual `.venv` (si no existe).
3. Instala `torch` en su versión solo CPU (~200 MB; la versión con GPU pesa ~2,5 GB y
   no hace falta).
4. Instala las dependencias de `requirements.txt`.
5. Crea `.env` a partir de `.env.example` (si no existe).
6. Genera un `AUTH_SECRET` aleatorio en `.env` (si está vacío). No se muestra.
7. Genera la base `db\anticipa.db` (si no existe).
8. Prepara el índice del RAG: descarga el modelo de embeddings (~195 MB, solo la
   primera vez). Sin internet, avisa y sigue: la API usa un motor de respaldo.
9. Ejecuta las pruebas (`pytest`). Si todo está bien, termina en verde.

La primera vez tarda varios minutos (descargas). Si un paso falla, se detiene y dice
cuál fue.

### `regenerar_base.bat`

Borra `db\anticipa.db` y la crea de nuevo con datos fijos, **usando los correos de
prueba de tu `.env`**. Pide confirmación porque se pierden los casos que hayas
registrado al probar. Al terminar, muestra los clientes de prueba (lo mismo que
`clientes_prueba.bat`).

- `regenerar_base.bat --publico`: ignora tus correos (todos quedan en `.example`).
- Si `run.bat` está abierto, detenlo antes (`Ctrl+C`): con la base en uso no se puede borrar.

### `run.bat`

Levanta la API en `http://127.0.0.1:8000` (o en otro puerto: `run.bat 8001`).

- Comprueba que existan `.venv` y `.env` (si no, pide ejecutar `install.bat`).
- Avisa si el puerto ya está ocupado y sugiere otro.
- Muestra las direcciones útiles: `/docs` (documentación interactiva) y, con
  `ENTORNO=dev`, `/dev/rag` (banco de pruebas del RAG).
- Se detiene con `Ctrl+C`.

### `clientes_prueba.bat`

Muestra los 13 clientes de prueba, que son los que tienen las casuísticas sembradas.
Solo lee la base: no cambia nada.

| Comando | Qué hace |
|---|---|
| `clientes_prueba.bat` | Los 13 clientes |
| `clientes_prueba.bat 2` | Solo los de tu slot (1 a 5) |
| `clientes_prueba.bat copiar 7` | Copia el RUC del cliente 7 al portapapeles, para pegarlo en `/docs` o en `demo_otp` |

Ejemplo (`clientes_prueba.bat 2`):

```
 #  RUC          Razón social                        Casuística    Slot  Correo
 2  99309114170  Distribuidora Pacífico Norte S.A.   CS-02            2  tu.correo@gmail.com
 7  99672731778  Logística Rápida del Callao S.A.C.  CS-09            2  tu.correo@gmail.com
12  99079819331  Seguros Atlántico Perú S.A.         CS-13            2  tu.correo@gmail.com

Casuísticas:
  CS-02  Servicio dado de baja que se sigue facturando
  CS-09  Variación fuerte de facturación (explicable)
  CS-13  Pedido fuera de alcance (renegociar tarifa)
RUC inexistente para probar CS-12: 99000000001 (...)
```

| Columna | Significado |
|---|---|
| `#` | Número de cliente (`id_cliente`) |
| `RUC` | El que se escribe para identificarse. **No cambia** al regenerar la base: es el mismo para todo el equipo |
| `Razón social` | Nombre de la empresa |
| `Casuística` | Qué situación tiene sembrada (factura duplicada, baja facturada, etc.), para saber qué preguntar. El cliente 11 no tiene ninguna: sirve de control |
| `Slot` | A qué `CORREO_PRUEBA_n` del `.env` está asociado |
| `Correo` | A dónde llega el código OTP. `(no recibe)` = correo `.example`: pon tu correo en tu slot y ejecuta `regenerar_base.bat` |

Dos casos especiales, que el script también indica:

- **Cliente 13 (CS-12):** tiene en su historial un intento bloqueado por 3 códigos
  incorrectos. Ese bloqueo es de aquella verificación: si pides un código nuevo, puede
  ingresar.
- **RUC `99000000001`:** no existe. Sirve para comprobar que la respuesta es la misma
  que con un RUC válido (no se revela qué RUC son clientes) y que no llega correo.

Con doble clic (o desde PowerShell), espera una tecla al final para que la ventana no
se cierre antes de leerla. Desde PowerShell se escribe con `.\` delante:
`.\clientes_prueba.bat 2`.

---

## Primera vez

**Requisitos:** Windows, [Git](https://git-scm.com/) y
[Python 3.12](https://www.python.org/downloads/) (sirve 3.10 o superior; marca
"Add Python to PATH" al instalarlo).

1. **Clona el repositorio** y entra a la carpeta:

   ```powershell
   git clone https://github.com/Guillermo112/Proyecto_DMC_Chat_bot.git
   cd Proyecto_DMC_Chat_bot
   ```

2. **Ejecuta `install.bat`.** Espera a que termine en verde.

3. **Completa tu `.env`** (lo creó el paso anterior; ábrelo con cualquier editor):

   | Variable | Qué poner |
   |---|---|
   | `CORREO_PRUEBA_n` | Tu correo, en **tu slot** `n` (1 a 5; acuérdenlo en el equipo, uno por integrante). Ahí te llegará el código OTP |
   | `NOMBRE_PRUEBA_n` | Tu nombre (opcional; el chat te saluda con él) |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_REMITENTE` | La cuenta que **envía** los códigos. Con Gmail: `smtp.gmail.com`, `587` y una [contraseña de aplicación](https://myaccount.google.com/apppasswords) (no tu contraseña normal) |
   | `ENTORNO` | Déjalo en `dev` (ya viene así): habilita el banco de pruebas y el CRUD de desarrollo |
   | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | El modelo del chat. Para DeepSeek: `https://api.deepseek.com`, la clave del equipo y el modelo acordado. Sin esto, todo funciona salvo `/chat` |

   No cambies `AUTH_SECRET`: lo generó `install.bat`. El resto de variables tiene
   valores por defecto (ver [Variables de entorno](#variables-de-entorno-env)).

4. **Ejecuta `regenerar_base.bat`.** `install.bat` creó la base **antes** de que pusieras
   tu correo, así que tus clientes de prueba todavía tienen correos `.example`. Al
   terminar verás los clientes de prueba: los de tu slot deben mostrar tu correo.
   Para volver a verlos más tarde: `clientes_prueba.bat`.

5. **Ejecuta `run.bat`** y abre en el navegador:
   - `http://127.0.0.1:8000/health` → debe responder `{"status": "OK", "db": "OK"}`.
   - `http://127.0.0.1:8000/docs` → documentación interactiva de la API.
   - `http://127.0.0.1:8000/chat` → **el chat**: identifícate con un RUC de tu slot y el
     código que llega a tu correo. Qué preguntarle a cada cliente y qué debería
     responder: [`docs/guion_demo.md`](docs/guion_demo.md).
   - `http://127.0.0.1:8000/dev/rag` → banco de pruebas del RAG.

   Al arrancar, la API carga el índice del RAG en segundo plano (~10 s); si escribes
   antes, el primer mensaje espera a que termine.

6. **(Opcional) Prueba el código OTP** con un RUC de tu slot, en otra terminal:

   ```powershell
   .\clientes_prueba.bat copiar 1
   ```

   ```powershell
   .venv\Scripts\python -X utf8 -m scripts.demo_otp
   ```

   Pega el RUC cuando lo pida (cambia `1` por un cliente de tu slot).

---

## Día a día

- **Levantar la API:** `run.bat` (otro puerto: `run.bat 8001`). Detener: `Ctrl+C`.
- **Correr las pruebas:**

  ```powershell
  .venv\Scripts\python -m pytest -q
  ```

- **Probar el chat con el modelo real, caso por caso** (necesita `LLM_*`; corre sobre
  una copia de la base y no envía correos; con `deepseek-flash` cuesta menos de un centavo):

  ```powershell
  .venv\Scripts\python -X utf8 -m scripts.probar_chat
  ```

  Recorre 11 casos (CS-01, 02, 06, 09, 10, 11, 13, glosario, fuera de tema, otro RUC e
  intento de cambiar las reglas). Por cada uno revisa que use la herramienta esperada,
  que cite los datos sembrados (de `db/casos_datos.json`) y que no diga frases
  prohibidas del modo A. `--detalle` muestra las respuestas; `CS-01 CS-13` corre solo
  esos casos.

- **Desarrollar con recarga automática** (reinicia la API al guardar un `.py`):

  ```powershell
  .venv\Scripts\python -m uvicorn app.main:app --reload
  ```

---

## Cuándo hacer qué

| Si pasa esto | Haz esto |
|---|---|
| Descargaste el proyecto por primera vez | [Primera vez](#primera-vez), pasos 1 a 5 |
| Necesitas un RUC para probar | `clientes_prueba.bat` (o `clientes_prueba.bat copiar N`) |
| No sabes qué preguntarle al chat, o vas a ensayar la demo | [`docs/guion_demo.md`](docs/guion_demo.md): preguntas por cliente y el guion de 5 minutos |
| Pusiste o cambiaste tu correo (`CORREO_PRUEBA_n`) o tu nombre en `.env` | `regenerar_base.bat` |
| Quieres ver llegar el aviso de un caso derivado | `CORREO_DERIVACIONES` con tu correo y `NOTIFICAR_DERIVACIONES=true` (solo en `ENTORNO=dev`), y reiniciar `run.bat` |
| Hiciste `git pull` y cambió `requirements.txt` | `install.bat` (instala solo lo que falta) |
| Hiciste `git pull` y cambió `db/schema.sql` o `db/generar_datos.py` | `regenerar_base.bat` |
| Falla una prueba que pide regenerar la base (p. ej. `test_la_base_admite_el_canal_web`) | `regenerar_base.bat` |
| Hiciste `git pull` y cambió `.env.example` | Revisa qué variable es nueva. Solo cópiala a tu `.env` si quieres cambiar su valor: todas tienen valor por defecto, salvo los correos y las claves |
| Cambiaste `SMTP_*`, `ENTORNO` u otra variable | Reinicia `run.bat` (`Ctrl+C` y de nuevo) |
| Cambiaste `AUTH_SECRET` (no deberías) | `regenerar_base.bat`, y vuelve a pedir el código: las sesiones abiertas dejan de valer |
| Borraste `.venv` o algo dejó de funcionar | `install.bat` |
| `run.bat` dice que el puerto está ocupado | Cierra el otro servidor o usa `run.bat 8001` |
| No llegan los códigos OTP | Revisa `SMTP_*`, tu `CORREO_PRUEBA_n` y que hayas ejecutado `regenerar_base.bat` después; revisa también spam |
| Cambiaste el prompt, las herramientas o el modelo, o se acerca una demo | `scripts.probar_chat` (ver [Día a día](#día-a-día)) |
| El chat responde "El asistente no está disponible" | Revisa `LLM_BASE_URL`, `LLM_API_KEY` y `LLM_MODEL` en `.env` (el mensaje dice si falta o si la clave es inválida) y reinicia `run.bat` |

---

## Variables de entorno (`.env`)

La app lee `.env` de la raíz del proyecto. **No se versiona**: cada integrante tiene el
suyo. `.env.example` es solo la plantilla: la app no lo lee, y si cambia no actualiza tu
`.env`. Si una variable también está definida en el sistema, gana la del sistema.

### Las que completas tú

| Variable | Uso |
|---|---|
| `CORREO_PRUEBA_1` … `CORREO_PRUEBA_5` | Correo de cada integrante para recibir el OTP. Clientes por slot: 1 → 1, 6, 11 · 2 → 2, 7, 12 · 3 → 3, 8, 13 · 4 → 4, 9 · 5 → 5, 10. Vacío = esos clientes quedan con `facturacion@clienteNN.example`. Requiere `regenerar_base.bat` |
| `NOMBRE_PRUEBA_1` … `NOMBRE_PRUEBA_5` | Nombre del contacto (opcional; el chat saluda con el primer nombre) |
| `SMTP_HOST`, `SMTP_PORT` (`587`), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_REMITENTE` | Cuenta que envía el código OTP. Puerto 465 = SSL; otro = STARTTLS |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Modelo del chat (cualquier endpoint compatible; el equipo usa DeepSeek). Sin ellos, `/chat` responde que el asistente no está disponible. Respaldos: `LLM_2_*` … `LLM_9_*` |

### La que genera `install.bat`

| Variable | Uso |
|---|---|
| `AUTH_SECRET` | Clave del HMAC del código OTP y de la firma del token de sesión (mínimo 32 caracteres). Cambiarla invalida sesiones y códigos, y obliga a regenerar la base |

### De desarrollo

| Variable | Por defecto | Uso |
|---|---|---|
| `ENTORNO` | `prod` (la plantilla trae `dev`) | `dev` monta el CRUD `/api/...` y el banco de pruebas `/dev/rag`, **sin autenticación**. Otro valor o vacío los oculta |
| `NOTIFICAR_DERIVACIONES` | `false` | `true` avisa por correo al ejecutivo al registrar un caso (`POST /mi/casos`) |
| `CORREO_DERIVACIONES` | — | **Solo con `ENTORNO=dev`:** redirige todos los avisos a una casilla de prueba (el correo dice a quién iba). Fuera de dev se ignora y el aviso va al ejecutivo real, para que un `.env` de desarrollo no desvíe los casos de todos los clientes a una sola casilla. Pon tu correo para ver llegar los avisos de tus pruebas. Si falla el SMTP, el caso se registra igual |

### Con valor por defecto (cámbialas solo si sabes por qué)

| Variable | Por defecto | Uso |
|---|---|---|
| `ANTICIPA_DB_PATH` | `db/anticipa.db` | Ruta de la base (relativa a la raíz o absoluta) |
| `LIMITE_POR_DEFECTO`, `LIMITE_MAXIMO` | `20`, `100` | Paginación de facturas |
| `OTP_MINUTOS_VALIDEZ`, `OTP_MAX_INTENTOS`, `OTP_ESPERA_REENVIO_SEG` | `10`, `3`, `60` | Vigencia del código, intentos y espera entre envíos |
| `AUTH_MINUTOS_SESION` | `30` | Duración del token de sesión |
| `AUTH_MAX_SOLICITUDES_POR_IP`, `AUTH_VENTANA_SOLICITUDES_SEG` | `5`, `900` | Límite de solicitudes de código por IP |
| `RAG_PDFS` | PDF 01 y 03 | PDF de `docs/` que se indexan, separados por coma |
| `RAG_CATALOGO` | `catalogo.json` | Catálogo que se indexa (con lista blanca de campos) |
| `RAG_MOTOR` | `auto` | `auto` (embeddings y, si no están, TF-IDF) · `denso` · `tfidf` (rápido, sin modelo) |
| `SENTENCE_TRANSFORMER_MODEL` | `ibm-granite/granite-embedding-97m-multilingual-r2` | Modelo de embeddings |
| `RAG_UMBRAL`, `RAG_UMBRAL_TFIDF` | `0.82`, `0.08` | Similitud mínima para usar un fragmento (cada motor tiene su escala) |
| `RAG_K_INICIAL`, `RAG_K_FINAL` | `8`, `3` | Candidatos recuperados y fragmentos que llegan al prompt |
| `RAG_MMR_LAMBDA` | `0.5` | 1 = solo relevancia, 0 = solo variedad |
| `RAG_PRECARGAR` | `true` | Cargar el índice al arrancar la API (en segundo plano) y no en el primer mensaje |
| `CHAT_MAX_VUELTAS` | `3` | Llamadas al modelo con herramientas por turno (más una para cerrar) |
| `CHAT_MAX_MENSAJES` | `8` | Mensajes previos que se reenvían en cada turno: más memoria, más tokens |
| `CHAT_MAX_CONVERSACIONES` | `200` | Conversaciones que se guardan en memoria a la vez; al pasar el tope se olvida la más antigua |
| `CHAT_MAX_TOKENS`, `CHAT_TEMPERATURA` | `600`, `0.3` | Largo máximo y variabilidad de cada respuesta del modelo |
| `CHUNK_MAX_PALABRAS`, `CHUNK_OVERLAP_PALABRAS` | `150`, `25` | Tamaño y solape de los fragmentos de prosa |

---

## Instalación manual (sin `.bat`, Linux o macOS)

Lo mismo que hacen los `.bat`, paso a paso:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
# Edita .env: AUTH_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))"),
# tu CORREO_PRUEBA_n y SMTP_*
python -X utf8 db/generar_datos.py   # = regenerar_base.bat (termina con validaciones OK)
python -X utf8 -m scripts.preparar_rag
python -m pytest -q
python -m uvicorn app.main:app       # = run.bat
```

`db/generar_datos.py` **borra la base existente** antes de recrearla y necesita
`AUTH_SECRET`. `-X utf8` evita errores de codificación en consolas Windows.

---

## Estructura del proyecto

```
install.bat, run.bat, regenerar_base.bat, clientes_prueba.bat   # scripts de Windows
app/
  main.py        # FastAPI: /health, /auth, /mi; con ENTORNO=dev, /api y /dev/rag
  config.py      # configuración desde variables de entorno (.env)
  auth/          # identificación por RUC + código OTP y token de sesión
  api/           # rutas del cliente autenticado (/mi) y banco de pruebas (/dev/rag)
  data/          # acceso a SQLite (solo lectura, filtrado por cliente)
  schemas/       # modelos Pydantic
  llm/           # cliente del modelo de lenguaje (router del curso)
  rag/           # RAG: lectura de PDF, filtro de modo A, índice y búsqueda
  static/        # página del banco de pruebas
  agente/        # prompt del sistema y turno del chat (RAG previo + herramientas)
  tools/         # herramientas del agente: datos del cliente desde app/data
db/              # schema.sql, generar_datos.py y la base generada (anticipa.db)
docs/            # PDF de conocimiento y documentación de la capa de datos
scripts/         # demo_otp.py, preparar_rag.py, clientes_prueba.py, probar_chat.py
tests/           # pytest
catalogo.json    # catálogo de casuísticas, servicios y políticas
faq.json         # preguntas frecuentes (pendiente de alinear con el modo A)
```

---

## Referencia

### Identificación por OTP (`app/auth`)

`solicitar_codigo(ruc)` envía un código de 6 dígitos **solo** al correo
registrado del cliente (vence en 10 min, se espera 60 s entre envíos) y
devuelve `(id_verificacion, correo_enmascarado)`; `verificar_codigo(id, codigo)`
devuelve el `cliente_id` o `None` (3 intentos fallidos = bloqueado). Solo se
guarda HMAC-SHA256(`AUTH_SECRET`, código) en `verificacion`; sin `AUTH_SECRET`
(mínimo 32 caracteres) no se envían códigos (503). Cambiarlo invalida los pendientes.

Por HTTP (`app/auth/rutas.py`):

- `POST /auth/solicitar-codigo` `{"ruc": "..."}` → `{"id_verificacion", "mensaje"}`.
  La respuesta es la misma (200, id nuevo, mismo mensaje) exista o no el RUC,
  también al pedir otro código antes de `OTP_ESPERA_REENVIO_SEG`: en ese caso no se
  envía correo y el código que ya llegó sirve con el **último** id devuelto (hereda
  intentos y expiración). 422 si el RUC no tiene 11 dígitos, 429 si la IP superó
  `AUTH_MAX_SOLICITUDES_POR_IP` solicitudes (5) en `AUTH_VENTANA_SOLICITUDES_SEG`
  segundos (900), con cabecera `Retry-After`; 503 si falla el correo. El límite
  por IP vive en memoria: con varios workers de uvicorn cada uno cuenta por su lado.
- `POST /auth/verificar-codigo` `{"id_verificacion", "codigo"}` →
  `{"verificado": true, "cliente_id", "access_token", "token_type": "bearer", "expira_en"}`
  o 401. `access_token` es un JWT (HS256, firmado con `AUTH_SECRET`) que vence en
  `AUTH_MINUTOS_SESION` minutos (30 por defecto). No hay logout: un token no se puede
  anular antes de vencer, salvo cambiando `AUTH_SECRET` (cierra todas las sesiones).
- `GET /auth/sesion` con `Authorization: Bearer <access_token>` → `{"cliente_id"}`,
  o 401 si falta, es inválido o expiró.

En el código, las rutas con datos de cliente toman el cliente de la sesión con
`cliente_id: int = Depends(cliente_actual)` (`app/auth/sesion.py`), nunca de lo que
escriba el usuario.

**Probar en vivo:** con tu correo en tu slot y la base regenerada (ver
[Primera vez](#primera-vez)), ejecuta `.venv\Scripts\python -X utf8 -m scripts.demo_otp`
e ingresa un RUC de tu slot, p. ej. `99813998698` (cliente 1, slot 1) o `99309114170`
(cliente 2, slot 2). La lista completa: `clientes_prueba.bat`.

### API del cliente autenticado (`/mi/...`)

Todas exigen `Authorization: Bearer <access_token>` (401 si falta o venció). El
cliente sale **solo** del token: ninguna ruta recibe `cliente_id`, así que no se
pueden pedir datos de otro cliente (`app/api/cliente.py`, sobre `app/data/facturacion.py`).

| Ruta | Devuelve |
|---|---|
| `GET /mi/perfil` | Datos del cliente y su ejecutivo |
| `GET /mi/facturas?periodo&fecha_desde&fecha_hasta&estado&limite&offset` | Facturas propias paginadas; `periodo` (AAAA-MM) es el mes facturado |
| `GET /mi/facturas/{numero}` | Cabecera y líneas; 404 si no existe **o es de otro cliente** |
| `GET /mi/saldo` | Saldo pendiente y notas de crédito aplicadas |
| `GET /mi/resumen?fecha_desde&fecha_hasta` | Totales por periodo (excluye anuladas) |
| `POST /mi/casos` | Registra y deriva un caso al ejecutivo (modo A); 201 creado, 200 si ya existía |
| `GET /mi/casos` | Casos del cliente y su estado |
| `GET /mi/solicitudes?estado` | Solicitudes con días transcurridos y si están fuera de plazo (CS-06) |
| `GET /mi/anomalias` | Anomalías detectadas (CS-01 a CS-05, CS-07) con su monto observado sin IGV |
| `GET /mi/servicios?estado` | Servicios contratados (incluye los dados de baja): tarifa pactada, SLA, alta y baja |
| `GET /mi/comparar?periodo_b&periodo_a` | Qué cambió entre dos periodos (por defecto, frente al mes anterior); con facturas duplicadas responde un aviso sin comparar |

Qué ruta usar según lo que pide el cliente (casuísticas CS-01 a CS-13 del PDF):
[`docs/casuisticas_api.md`](docs/casuisticas_api.md).

### Rutas de desarrollo (solo con `ENTORNO=dev`)

Sin autenticación: no exponer fuera de tu computadora.

- `/api/...`: CRUD de todas las tablas, para Postman. La tabla `verificacion` no
  está: solo se toca vía `/auth`.
- `/dev/rag`: banco de pruebas del RAG (página web). `GET /dev/rag/buscar?q=` y
  `GET /dev/rag/info` son sus endpoints.

Con cualquier otro valor de `ENTORNO`, o sin definirlo, quedan únicamente `/health`,
`/auth` y `/mi`.

### Chat (`/chat` y `POST /mi/chat`)

La página `/chat` hace la identificación (RUC + código) y conversa con
`POST /mi/chat` (`{"mensaje", "conversacion_id"}`, con el token). Cada turno
(`app/agente/chat.py`):

0. **Saludo** (`POST /mi/chat/saludo`, al entrar o al empezar una conversación nueva):
   sin modelo y sin costo. Saluda por el nombre del contacto, revisa la cuenta y, si hay
   anomalías sin caso, las menciona y ofrece explicarlas (si ya tienen caso, recuerda
   que siguen en revisión); si no, pregunta qué quiere hacer hoy. Queda en el historial,
   así el modelo entiende un "sí, explícamelo".
1. **RAG previo:** busca en el índice (local, sin costo). Si algún fragmento pasa el
   umbral, lo agrega como contexto. No gasta una llamada al modelo para decidirlo.
2. **Modelo con herramientas:** el prompt del sistema (`app/agente/prompt.py`, lo
   esencial del PDF 01) más 10 herramientas (`app/tools`): perfil, facturas, detalle,
   saldo, anomalías, servicios, comparar periodos, solicitudes, registrar caso y
   listar casos. El `cliente_id` lo pone el código desde el token; si el modelo lo
   manda, se ignora.
3. **Tope de vueltas** (`CHAT_MAX_VUELTAS`): cada herramienta pedida es una llamada
   más; al llegar al tope, una última llamada sin herramientas cierra la respuesta.
4. **Memoria corta:** se reenvían los últimos `CHAT_MAX_MENSAJES` textos de la
   conversación (sin resultados de herramientas). Vive en memoria: se pierde al
   reiniciar la API. `DELETE /mi/chat/{conversacion_id}` la olvida.

La respuesta trae la traza que muestra el panel de la página: herramientas usadas
(con sus datos), documentos citados, llamadas al modelo y tokens (con los que DeepSeek
sirvió desde su caché, que cobra más barato).

**Costo aproximado por turno:** ~3 400 tokens de entrada por llamada (prompt ~900,
herramientas ~1 000, historial y contexto). Una pregunta de datos usa 2 llamadas
(pedir la herramienta y responder); una de glosario, 1.

### RAG (`app/rag`)

Recupera conocimiento general para que el agente lo cite. Detalle de decisiones y
pendientes en [`PENDIENTES_rag.md`](PENDIENTES_rag.md), sección 3.

- **Fuentes:** `docs/Anticipa_01_*.pdf`, `docs/Anticipa_03_*.pdf` y `catalogo.json`.
  `faq.json` no entra al índice (tendrá su propio clasificador).
- **PDF** (`pdf.py`): separa prosa y tablas; la prosa se corta por oraciones y cada
  fila de tabla es un fragmento.
- **Filtro de modo A** (`ingesta.py`): de `catalogo.json` entran solo los campos de una
  lista blanca; lo que describe acciones del modo B se quita por oración o por columna
  en los PDF, y hace fallar la ingesta si aparece en el JSON.
- **Índice** (`indice.py`): embeddings locales (granite 97M) con respaldo TF-IDF,
  umbral de similitud y MMR (fragmentos relevantes y variados).
- **Banco de pruebas** (`/dev/rag`): muestra qué recupera cada pregunta, su puntaje,
  si pasa el umbral y qué llegaría al prompt. Permite mover el umbral y el MMR sin
  reiniciar y copiar el historial como CSV para calibrar.

### Capa de datos (`app/data`)

Todas las funciones reciben `cliente_id` y lo aplican en el `WHERE`; ninguna
devuelve datos de otro cliente. La conexión se abre en solo lectura y todas las
consultas son parametrizadas; la única escritura es `registrar_caso`.

| Función | Descripción |
|---|---|
| `obtener_cliente` | Datos del cliente y su ejecutivo, o `None` |
| `listar_facturas` | Facturas por periodo, fecha de emisión y estado; paginado con tope |
| `detalle_factura` | Cabecera + líneas; `None` si la factura es de otro cliente |
| `saldo_pendiente` | Suma de facturas emitidas, vencidas o en disputa |
| `resumen_facturacion` | Totales por periodo (excluye anuladas) |
| `obtener_servicios` | Servicios contratados, con tarifa pactada, SLA, alta y baja |
| `comparar_periodos` | Diferencias entre dos periodos |
| `detectar_anomalias` | Anomalías CS-01 a CS-05 y CS-07 con su monto observado |
| `consultar_solicitudes` | Solicitudes y su plazo de atención (CS-06) |
| `registrar_caso`, `listar_casos` (`casos.py`) | Registrar y derivar un caso; listar los del cliente |

Detalle de cada función y su relación con las casuísticas:
[`docs/capa_datos.md`](docs/capa_datos.md).

### Notas sobre los datos

- `anticipa.db` no se versiona: se genera de forma reproducible desde `db/schema.sql`
  con datos fijos (`regenerar_base.bat`). Todo es ficticio: los RUC empiezan con 99.
- La fecha de sistema es ficticia (`parametro.fecha_actual` = 2026-12-05); el
  saldo vencido se calcula contra ella, no contra la fecha real.
- No hay tabla de pagos: el saldo se deriva del estado de la factura.
- Las notas de crédito aplicadas no modifican la factura; `saldo_pendiente`
  no las resta y las informa aparte en `notas_credito_aplicadas`.
- La factura duplicada F001-000254/255 (casuística CS-01) está a propósito
  en la base y suma dos veces en el saldo del cliente 1.
